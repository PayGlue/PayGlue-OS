# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import hashlib
import hmac
import json
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError
from django.db import transaction
from django.http import Http404, HttpResponse as DjangoHttpResponse
from django.views import View
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from payglue_backend.authn.authentication import FirebaseBearerAuthentication
from payglue_backend.authn.rbac import (
    TenantReadOwnerAdminWrite,
    resolve_tenant_membership,
)
from payglue_backend.core.errors import MissingCredentialsError, PlanLimitExceededError
from payglue_backend.core.models import TenantContext
from payglue_backend.http.throttling import DynamicScopedRateThrottle
from payglue_backend.tenants.audit import write_public_audit_event
from payglue_backend.tenants.models import PublicAuditEvent, Tenant, TenantMembership
from payglue_backend.tenants.plan_limits import check_resource_limit
from payglue_backend.tenants.serializers import PublicAuditEventSerializer
from payglue_backend.webhooks import wiring
from payglue_backend.webhooks.models import BuyButton, IntegrationConfig, PaywallConfig, PricingTable, PricingTier, ProductMapping
from payglue_backend.webhooks.models import WebhookInboundEvent
from payglue_backend.webhooks.test_events import run_mapping_test
from payglue_backend.webhooks.serializers import (
    IntegrationCredentialsSerializer,
    IntegrationConfigSerializer,
    ProductMappingSerializer,
    WebhookInboundEventSerializer,
)
from payglue_backend.webhooks.tasks import process_inbound_webhook_event


def _enforce_resource_limit(tenant_slug: str, resource: str) -> Response | None:
    """Return a 402 Response if `tenant_slug`'s plan limit for `resource`
    is exceeded, else None (including when the tenant can't be resolved --
    permission classes have already gated access by this point)."""
    tenant = Tenant.objects.filter(slug=tenant_slug).select_related("billing_account__plan").first()
    if tenant is None:
        return None
    try:
        check_resource_limit(tenant, resource)
    except PlanLimitExceededError as exc:
        plan_key = tenant.billing_account.plan.key if tenant.billing_account else None
        return Response(
            {"detail": str(exc), "upgrade_required": True, "plan": plan_key},
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )
    return None


# TODO: Add owner/admin replay endpoint for dead-letter webhook events.
class WebhookIngestView(APIView):
    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "webhook_ingest"

    _HEADER_ALLOWLIST = {
        "content-type",
        "polar-signature",
        "webhook-id",
        "webhook-timestamp",
        "webhook-signature",
        "x-signature",
        "paypal-transmission-id",
        "paypal-transmission-time",
        "paypal-cert-url",
        "paypal-auth-algo",
        "paypal-transmission-sig",
    }

    # Each provider names/nests its raw event-type marker differently in its
    # webhook payload -- this is NOT the canonical event type used elsewhere
    # (e.g. Paddle's raw "transaction.completed" maps to canonical
    # "order.paid"). Gumroad has no explicit type field at all, so it's
    # intentionally absent here and always falls through to full processing.
    _RAW_EVENT_TYPE_FIELDS = {
        "polar": "type",
        "paypal": "event_type",
        "paddle": "event_type",
    }

    @classmethod
    def _extract_raw_event_type(cls, payment_provider: str, payload: dict) -> str | None:
        if payment_provider == "lemonsqueezy":
            meta = payload.get("meta")
            if isinstance(meta, dict):
                event_name = meta.get("event_name")
                return event_name if isinstance(event_name, str) and event_name else None
            return None
        if payment_provider == "kofi":
            # Ko-fi's form-encoded body has a single 'data' field holding a
            # JSON string -- the payload_snapshot dict() pass in post() below
            # never unwraps it, so decode it here to reach the 'type' field.
            raw_data = payload.get("data")
            if not isinstance(raw_data, str):
                return None
            try:
                parsed = json.loads(raw_data)
            except json.JSONDecodeError:
                return None
            if not isinstance(parsed, dict):
                return None
            event_type = parsed.get("type")
            return event_type if isinstance(event_type, str) and event_type else None
        field = cls._RAW_EVENT_TYPE_FIELDS.get(payment_provider)
        if not field:
            return None
        value = payload.get(field)
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _redacted_endpoint_path(tenant_slug: str, payment_provider: str) -> str:
        return f"/t/{tenant_slug}/webhooks/{payment_provider}/[redacted]/"

    @staticmethod
    def _endpoint_token_hash(endpoint_token: str) -> str:
        digest = hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            endpoint_token.encode("utf-8"),
            hashlib.sha256,
        )
        return digest.hexdigest()

    def _snapshot_headers(self, request: Request) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        max_value_length = int(getattr(settings, "WEBHOOK_HEADER_MAX_CHARS", 512))
        for key, value in request.headers.items():
            if key.lower() not in self._HEADER_ALLOWLIST:
                continue
            snapshot[key] = value[:max_value_length]
        return snapshot

    def post(
        self,
        request: Request,
        tenant_slug: str,
        payment_provider: str,
        endpoint_token: str,
    ) -> Response:
        tenant_ctx = getattr(request, "tenant_ctx", None)
        if (
            not isinstance(tenant_ctx, TenantContext)
            or tenant_ctx.tenant_slug != tenant_slug
        ):
            return Response(
                {"detail": "Tenant context was not resolved from request path."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not wiring.validate_endpoint_token(
            tenant_slug,
            payment_provider,
            endpoint_token,
        ):
            return Response(
                {"detail": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if payment_provider not in wiring.get_supported_payment_provider_keys():
            return Response(
                {"detail": f"Unsupported payment provider '{payment_provider}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_body_size = int(getattr(settings, "WEBHOOK_MAX_BODY_BYTES", 65536))
        if len(request.body) > max_body_size:
            return Response(
                {"detail": "Webhook payload too large."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        payload_snapshot = None
        if request.content_type == "application/json":
            try:
                payload_snapshot = json.loads(request.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload_snapshot = None
        elif request.content_type == "application/x-www-form-urlencoded":
            # Gumroad (and some other providers) POST form-encoded, not JSON.
            # Decode it too so the Events UI can show something other than
            # "null" for debugging -- this is display-only, the real
            # processing pipeline always re-parses payload_raw itself.
            try:
                from urllib.parse import parse_qsl

                pairs = parse_qsl(request.body.decode("utf-8"), keep_blank_values=True)
                payload_snapshot = dict(pairs) if pairs else None
            except UnicodeDecodeError:
                payload_snapshot = None

        # Skip storing events whose type we don't support — return 200 immediately
        # to silence retries and avoid polluting the DB with irrelevant records.
        if isinstance(payload_snapshot, dict):
            raw_event_type = self._extract_raw_event_type(payment_provider, payload_snapshot)
            if raw_event_type:
                try:
                    adapter = wiring.get_payment_adapter(payment_provider)
                    supports_raw_event_type = getattr(adapter, "supports_raw_event_type", None)
                    if supports_raw_event_type and not supports_raw_event_type(raw_event_type):
                        return Response(
                            {"status": "ignored", "event_type": raw_event_type},
                            status=status.HTTP_200_OK,
                        )
                except Exception:
                    pass  # If adapter lookup fails, proceed to store as normal

        inbound_event = WebhookInboundEvent.objects.create(
            tenant_slug=tenant_slug,
            provider=payment_provider,
            status=WebhookInboundEvent.Status.RECEIVED,
            payload_raw=request.body,
            payload_snapshot=payload_snapshot,
            headers_snapshot=self._snapshot_headers(request),
            endpoint_path=self._redacted_endpoint_path(tenant_slug, payment_provider),
            endpoint_token_hash=self._endpoint_token_hash(endpoint_token),
            endpoint_metadata={
                "method": request.method,
                "content_type": request.content_type or "",
            },
        )
        try:
            process_inbound_webhook_event.delay(
                inbound_event.id,
                tenant_slug=tenant_slug,
            )
        except Exception:
            inbound_event.status = WebhookInboundEvent.Status.FAILED
            inbound_event.last_error = "queue publish failed"
            inbound_event.failed_at = timezone.now()
            inbound_event.save(
                update_fields=["status", "last_error", "failed_at", "updated_at"]
            )
            return Response(
                {"detail": "Webhook queue is unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {"status": "accepted", "tracking_id": inbound_event.id},
            status=status.HTTP_202_ACCEPTED,
        )


def _integration_provider_key_allowlist() -> dict[str, set[str]]:
    """Maps each valid IntegrationConfig provider_key to the provider_type
    values it accepts. Payment providers each get their own slot (keyed by
    their own name) so multiple payment providers can be connected on the
    same tenant simultaneously without overwriting each other's config --
    only "cms" remains a single shared slot, since a tenant has exactly one
    CMS.
    """
    allowed: dict[str, set[str]] = {"cms": wiring.get_supported_cms_provider_keys()}
    for key in wiring.get_supported_payment_provider_keys():
        allowed[key] = {key}
    return allowed


class TenantIntegrationConfigView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> None:
        pass

    def get(self, request: Request, tenant_slug: str, provider_key: str) -> Response:
        self._require_tenant_context(request, tenant_slug)
        integration = IntegrationConfig.objects.filter(
            tenant_slug=tenant_slug,
            provider_key=provider_key,
        ).first()
        if integration is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(IntegrationConfigSerializer(integration).data)

    def put(self, request: Request, tenant_slug: str, provider_key: str) -> Response:
        self._require_tenant_context(request, tenant_slug)
        allowed_provider_types = _integration_provider_key_allowlist()
        if provider_key not in allowed_provider_types:
            return Response(
                {"detail": "Unsupported provider key."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Only enforce on a genuinely new payment-provider connection -- "cms"
        # is a single always-present slot, not a plan-limited resource, and
        # updating an already-connected provider shouldn't be blocked.
        is_new_connection = not IntegrationConfig.objects.filter(
            tenant_slug=tenant_slug, provider_key=provider_key
        ).exists()
        if provider_key != "cms" and is_new_connection:
            limit_response = _enforce_resource_limit(tenant_slug, "payment providers")
            if limit_response is not None:
                return limit_response

        serializer = IntegrationConfigSerializer(
            data=request.data,
            context={
                "provider_key": provider_key,
                "allowed_provider_types": allowed_provider_types,
            },
        )
        serializer.is_valid(raise_exception=True)
        integration, _ = IntegrationConfig.objects.update_or_create(
            tenant_slug=tenant_slug,
            provider_key=provider_key,
            defaults={
                "enabled": serializer.validated_data["enabled"],
                "provider_type": serializer.validated_data["provider_type"],
                "metadata": serializer.validated_data.get("metadata", {}),
            },
        )
        return Response(IntegrationConfigSerializer(integration).data)


class TenantProductMappingView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> None:
        pass

    def get(self, request: Request, tenant_slug: str) -> Response:
        self._require_tenant_context(request, tenant_slug)
        mappings = ProductMapping.objects.filter(tenant_slug=tenant_slug).order_by("id")
        serializer = ProductMappingSerializer(
            instance=mappings,
            many=True,
            context={
                "allowed_payment_providers": wiring.get_supported_payment_provider_keys()
            },
        )
        return Response(serializer.data)

    def post(self, request: Request, tenant_slug: str) -> Response:
        self._require_tenant_context(request, tenant_slug)
        serializer = ProductMappingSerializer(
            data=request.data,
            context={
                "allowed_payment_providers": wiring.get_supported_payment_provider_keys()
            },
        )
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(tenant_slug=tenant_slug)
        except IntegrityError:
            return Response(
                {"detail": "Mapping already exists for this tenant scope."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def patch(self, request: Request, tenant_slug: str) -> Response:
        self._require_tenant_context(request, tenant_slug)
        mapping_id = request.query_params.get("mapping_id")
        if mapping_id is None or not mapping_id.isdigit():
            return Response(
                {"detail": "mapping_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            mapping = ProductMapping.objects.get(id=int(mapping_id), tenant_slug=tenant_slug)
        except ProductMapping.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = ProductMappingSerializer(
            instance=mapping,
            data=request.data,
            partial=True,
            context={"allowed_payment_providers": wiring.get_supported_payment_provider_keys()},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request: Request, tenant_slug: str) -> Response:
        self._require_tenant_context(request, tenant_slug)
        mapping_id = request.query_params.get("mapping_id")
        if mapping_id is None or not mapping_id.isdigit():
            return Response(
                {"detail": "mapping_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deleted, _ = ProductMapping.objects.filter(
            id=int(mapping_id),
            tenant_slug=tenant_slug,
        ).delete()
        if deleted == 0:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TenantIntegrationCredentialsView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "integration_credentials_write"

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> None:
        pass

    def put(self, request: Request, tenant_slug: str, provider_key: str) -> Response:
        self._require_tenant_context(request, tenant_slug)
        if provider_key not in _integration_provider_key_allowlist():
            return Response(
                {"detail": "Unsupported provider key."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        integration = IntegrationConfig.objects.filter(
            tenant_slug=tenant_slug,
            provider_key=provider_key,
        ).first()
        if integration is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = IntegrationCredentialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = serializer.validated_data["credentials"]

        tenant_ctx = TenantContext(tenant_slug=tenant_slug)
        provider = wiring.get_credential_provider()
        # Merge with existing credentials so partial updates (e.g. only webhook_secret)
        # do not silently delete other stored fields (e.g. access_token).
        try:
            existing = dict(provider.get_credentials(tenant_ctx, integration.provider_type))
        except Exception:
            existing = {}
        merged = {**existing, **{k: v for k, v in credentials.items() if v}}
        credential_ref = provider.set_credentials(
            tenant_ctx=tenant_ctx,
            provider_key=integration.provider_type,
            credentials=merged,
        )

        metadata = (
            dict(integration.metadata) if isinstance(integration.metadata, dict) else {}
        )
        metadata["credential_ref"] = {
            "backend": credential_ref.get("backend", "unknown"),
            "updated_at": credential_ref.get("updated_at", ""),
            "masked_keys": credential_ref.get(
                "masked_keys", sorted(credentials.keys())
            ),
        }
        # Persist non-secret fields from credentials into metadata so the frontend
        # can read them without decrypting. api_base_url is a public URL, not a secret.
        if "api_base_url" in merged and merged["api_base_url"]:
            metadata["api_base_url"] = merged["api_base_url"]
        integration.metadata = metadata
        integration.save(update_fields=["metadata", "updated_at"])

        tenant = Tenant.objects.filter(slug=tenant_slug).only("id").first()
        if tenant is not None:
            write_public_audit_event(
                tenant=tenant,
                actor_membership=resolve_tenant_membership(request),
                event_type=PublicAuditEvent.EventType.INTEGRATION_CREDENTIALS_WRITTEN,
                target_type="integration",
                target_id=provider_key,
                metadata={
                    "provider_key": provider_key,
                    "provider_type": integration.provider_type,
                    "credential_ref": metadata["credential_ref"],
                },
            )

        webhook_registration: dict[str, object] | None = None
        if integration.provider_type == "gumroad" and "access_token" in merged:
            # Gumroad has no dashboard page to paste a webhook URL into --
            # register it for the user automatically instead of requiring an
            # API call a real end user would never make.
            from payglue_backend.webhooks.adapters.gumroad import GumroadPaymentAdapter

            try:
                adapter = GumroadPaymentAdapter(credential_provider=provider)
                webhook_registration = adapter.register_webhook_subscriptions(
                    tenant_ctx,
                    f"https://api.payglue.io/webhooks/gumroad?tenant={tenant_slug}",
                )
            except Exception as exc:
                logger.warning("gumroad: webhook auto-registration failed: %s", exc)
                webhook_registration = {"registered": [], "failed": ["sale", "cancellation", "subscription_ended"]}

        response_body = {
            "provider_key": provider_key,
            "provider_type": integration.provider_type,
            "credential_ref": metadata["credential_ref"],
        }
        if webhook_registration is not None:
            response_body["webhook_registration"] = webhook_registration
        return Response(response_body)


class TenantIntegrationHealthView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "integration_health"

    @staticmethod
    def _is_owner_or_admin(request: Request) -> bool:
        membership = resolve_tenant_membership(request)
        if membership is None:
            return False
        return membership.role in {
            TenantMembership.Role.OWNER,
            TenantMembership.Role.ADMIN,
        }

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> None:
        pass

    @staticmethod
    def _save_health_result(
        integration: IntegrationConfig,
        health_result: dict[str, object],
    ) -> None:
        metadata = (
            dict(integration.metadata) if isinstance(integration.metadata, dict) else {}
        )
        metadata["health"] = health_result
        integration.metadata = metadata
        integration.save(update_fields=["metadata", "updated_at"])

    def get(self, request: Request, tenant_slug: str, provider_key: str) -> Response:
        self._require_tenant_context(request, tenant_slug)
        if not self._is_owner_or_admin(request):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
        integration = IntegrationConfig.objects.filter(
            tenant_slug=tenant_slug,
            provider_key=provider_key,
        ).first()
        if integration is None:
            return Response(
                {"detail": "Integration configuration was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not integration.enabled:
            return Response(
                {"detail": "Integration is disabled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        checked_at = timezone.now().isoformat()

        if integration.provider_key not in _integration_provider_key_allowlist():
            return Response(
                {"detail": "Unsupported provider key."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        adapter = None
        if integration.provider_key in wiring.get_supported_payment_provider_keys():
            if (
                integration.provider_type
                not in wiring.get_supported_payment_provider_keys()
            ):
                return Response(
                    {
                        "detail": (
                            "Unsupported payment provider type "
                            f"'{integration.provider_type}'."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            adapter = wiring.get_payment_adapter(integration.provider_type)
        else:
            if (
                integration.provider_type
                not in wiring.get_supported_cms_provider_keys()
            ):
                return Response(
                    {
                        "detail": (
                            f"Unsupported cms provider type '{integration.provider_type}'."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            adapter = wiring.get_cms_adapter(integration.provider_type)

        tenant_ctx = TenantContext(tenant_slug=tenant_slug)
        try:
            raw_result = adapter.health_check(tenant_ctx)
            ok = bool(raw_result.get("ok"))
            code = str(raw_result.get("code", "unknown"))
            message = str(raw_result.get("message", ""))
        except MissingCredentialsError as exc:
            ok = False
            code = "missing_credentials"
            message = str(exc)
        except Exception:
            ok = False
            code = "error"
            message = "Integration health check failed unexpectedly."

        result = {
            "ok": ok,
            "checked_at": checked_at,
            "code": code,
            "message": message,
        }
        self._save_health_result(integration, result)
        return Response(result)


class TenantGhostStripeStatusView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "integration_health"

    def get(self, request: Request, tenant_slug: str) -> Response:
        integration = IntegrationConfig.objects.filter(
            tenant_slug=tenant_slug, provider_key="cms", provider_type="ghost", enabled=True,
        ).first()
        if integration is None:
            return Response({"detail": "Ghost integration not configured."}, status=status.HTTP_404_NOT_FOUND)

        adapter = wiring.get_cms_adapter(integration.provider_type)

        tenant_ctx = TenantContext(tenant_slug=tenant_slug)
        try:
            result = adapter.stripe_status(tenant_ctx)
        except MissingCredentialsError:
            return Response({"connected": False, "error": "missing_credentials"})
        except Exception:
            return Response({"connected": False, "error": "request_failed"})

        return Response(result)


class CheckHeaderScriptView(APIView):
    """Check whether the paywall.js header script is present on the tenant's Ghost site."""
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "integration_health"

    def get(self, request: Request, tenant_slug: str) -> Response:
        integration = IntegrationConfig.objects.filter(
            tenant_slug=tenant_slug, provider_key="cms", provider_type="ghost", enabled=True,
        ).first()
        if integration is None:
            return Response({"installed": False, "error": "Ghost not connected.", "url": None})

        metadata = integration.metadata if isinstance(integration.metadata, dict) else {}
        site_url = metadata.get("api_base_url", "")
        if not site_url:
            return Response({"installed": False, "error": "Ghost site URL not found. Re-save your Ghost credentials.", "url": None})

        # Normalise to root URL and guard against SSRF to internal/private hosts
        from urllib.parse import urlparse
        import ipaddress
        parsed = urlparse(site_url)
        if parsed.scheme not in ("http", "https"):
            return Response({"installed": False, "error": "Ghost site URL must use http or https.", "url": None})
        hostname = parsed.hostname or ""
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return Response({"installed": False, "error": "Ghost site URL resolves to a private address.", "url": None})
        except ValueError:
            # hostname is a domain name — block obvious local targets
            if hostname.lower() in ("localhost", "localhost.localdomain") or hostname.lower().endswith(".internal") or hostname.lower().endswith(".local"):
                return Response({"installed": False, "error": "Ghost site URL must point to a public host.", "url": None})
        root_url = f"{parsed.scheme}://{parsed.netloc}/"

        import urllib.request

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        try:
            opener = urllib.request.build_opener(_NoRedirect)
            req = urllib.request.Request(root_url, headers={"User-Agent": "PayGlue-ScriptCheck/1.0"})
            with opener.open(req, timeout=8) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return Response({"installed": False, "error": f"Could not reach {root_url}: {e}", "url": root_url})

        installed = "api.payglue.io/paywall.js" in html
        return Response({"installed": installed, "url": root_url, "error": None})


_PAYWALL_JS = r"""(function(){
  var s=document.currentScript;
  var org=s&&s.getAttribute('data-org');
  if(!org){console.warn('[PayGlue] data-org missing on paywall script');return;}
  /* Guard: prevent double-init if script tag is included more than once */
  if(window.__payglueInit){return;}
  window.__payglueInit=true;
  var API='https://api.payglue.io';
  var DBG=typeof localStorage!=='undefined'&&localStorage.getItem('payglueDebug')==='1';
  function dbg(){if(DBG)console.log.apply(console,['[PayGlue]'].concat(Array.prototype.slice.call(arguments)));}
  var ROOTS='.gh-content,.post-content,.entry-content,.article-content,.kg-post-content,[class*="post-body"],[class*="article-body"]';

  function getRoot(el){return el.closest(ROOTS)||el.parentElement;}

  function getPivot(el,root){
    var p=el;
    while(p.parentElement&&p.parentElement!==root)p=p.parentElement;
    return p;
  }

  function buildCard(cfg){
    var color=cfg.button_color||'#4f46e5';
    var card=document.createElement('div');
    card.setAttribute('data-payglue-gate','');
    card.style.cssText='display:block;width:100%;margin:2rem 0;padding:2rem 1.75rem;background:#fff;border-top:4px solid '+color+';border-radius:0 0 8px 8px;box-shadow:0 4px 20px rgba(0,0,0,.08);font-family:inherit;box-sizing:border-box;';
    var h=document.createElement('div');
    h.setAttribute('data-payglue-headline','');
    h.textContent=cfg.headline||'Premium content';
    var p=document.createElement('div');
    p.setAttribute('data-payglue-body','');
    p.textContent=cfg.body||'Purchase access to continue reading.';
    card.appendChild(h);card.appendChild(p);
    if(cfg.button_url){
      if(cfg.button_url.indexOf('payglue-table:')===0){
        var tableId=cfg.button_url.replace('payglue-table:','');
        var btn=document.createElement('button');
        btn.textContent=cfg.button_text||'Get access';
        btn.style.cssText='display:inline-block;background:'+color+';color:#fff;padding:0.6em 1.75em;border-radius:0.4em;font-size:0.95em;font-weight:600;border:none;cursor:pointer;font-family:inherit;';
        btn.onmouseover=function(){this.style.opacity='0.85';};
        btn.onmouseout=function(){this.style.opacity='1';};
        btn.addEventListener('click',function(){
          fetch(API+'/api/v1/pricing-tables/'+tableId+'/public/')
            .then(function(r){return r.ok?r.json():null;})
            .then(function(tbl){if(tbl)openPricingTableOverlay(tbl);})
            .catch(function(){});
        });
        card.appendChild(btn);
      }else{
        var a=document.createElement('a');
        a.href=cfg.button_url;a.target='_blank';a.rel='noopener noreferrer';
        a.textContent=cfg.button_text||'Get access';
        a.style.cssText='display:inline-block;background:'+color+';color:#fff;padding:0.6em 1.75em;border-radius:0.4em;font-size:0.95em;font-weight:600;text-decoration:none;';
        a.onmouseover=function(){this.style.opacity='0.85';};
        a.onmouseout=function(){this.style.opacity='1';};
        card.appendChild(a);
      }
    }
    return card;
  }

  function openPricingTableOverlay(tbl){
    var acc=tbl.accent_color||'#4f46e5';
    var isYearly=false;
    var overlay=document.createElement('div');
    overlay.style.cssText='position:fixed;top:0;left:0;width:100%;height:100%;z-index:99999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.55);padding:1rem;box-sizing:border-box;overflow-y:auto;';
    function close(){if(document.body.contains(overlay))document.body.removeChild(overlay);}
    function render(){
      overlay.innerHTML='';
      var modal=document.createElement('div');
      modal.style.cssText='background:#fff;border-radius:16px;max-width:900px;width:100%;padding:clamp(1rem,4vw,2rem);position:relative;margin:auto;';
      var closeBtn=document.createElement('button');
      closeBtn.innerHTML='&times;';closeBtn.setAttribute('aria-label','Close');
      closeBtn.style.cssText='position:absolute;top:1rem;right:1rem;background:none;border:none;font-size:1.75rem;cursor:pointer;color:#64748b;line-height:1;padding:0;';
      closeBtn.onclick=close;modal.appendChild(closeBtn);
      if(tbl.show_toggle){
        var tWrap=document.createElement('div');tWrap.style.cssText='display:flex;justify-content:center;margin-bottom:1.5rem;';
        var mBtn=document.createElement('button');mBtn.textContent='Monthly';
        mBtn.style.cssText='padding:0.4em 1.25em;border:1px solid '+acc+';border-radius:0.4em 0 0 0.4em;font-size:0.85em;font-weight:600;cursor:pointer;transition:background .15s;'+(isYearly?'background:#fff;color:'+acc+';':'background:'+acc+';color:#fff;');
        var yBtn=document.createElement('button');yBtn.textContent='Yearly';
        yBtn.style.cssText='padding:0.4em 1.25em;border:1px solid '+acc+';border-left:none;border-radius:0 0.4em 0.4em 0;font-size:0.85em;font-weight:600;cursor:pointer;transition:background .15s;'+(isYearly?'background:'+acc+';color:#fff;':'background:#fff;color:'+acc+';');
        mBtn.onclick=function(){isYearly=false;render();};
        yBtn.onclick=function(){isYearly=true;render();};
        tWrap.appendChild(mBtn);tWrap.appendChild(yBtn);modal.appendChild(tWrap);
      }
      var grid=document.createElement('div');
      grid.style.cssText='display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;';
      tbl.tiers.forEach(function(tier){
        var hl=!!tier.highlighted;
        var card=document.createElement('div');
        card.style.cssText='border:'+(hl?'2px solid '+acc:'1px solid #e2e8f0')+';border-radius:12px;padding:1.25rem 1rem;position:relative;';
        if(tier.badge_text){
          var badge=document.createElement('div');badge.textContent=tier.badge_text;
          badge.style.cssText='position:absolute;top:-11px;left:50%;transform:translateX(-50%);background:'+acc+';color:#fff;font-size:0.7em;font-weight:700;padding:2px 10px;border-radius:100px;white-space:nowrap;';
          card.appendChild(badge);
        }
        var nameEl=document.createElement('div');nameEl.textContent=tier.name;
        nameEl.style.cssText='font-size:0.8em;font-weight:600;color:'+(hl?acc:'#64748b')+';margin-bottom:0.5rem;';
        card.appendChild(nameEl);
        var priceEl=document.createElement('div');priceEl.style.cssText='margin-bottom:0.5rem;';
        var _syms={'EUR':'€','USD':'$','GBP':'£','CHF':'CHF '};
        var _sym=_syms[tbl.currency||'EUR']||'€';
        if(tier.cta_type==='free_signup'){var _fr=document.createElement('span');_fr.textContent='Free';_fr.style.cssText='font-size:1.6em;font-weight:700;color:#0f172a;';priceEl.appendChild(_fr);}
        else{
          var price=isYearly?tier.price_yearly:tier.price_monthly;
          var period=tier.period;
          // price/period are free-text tenant config (CharField) -- build via
          // textContent, never innerHTML, so a value like "<img onerror=...>"
          // can't execute on the creator's site (matches the rest of this embed).
          if(price!==null&&price!==undefined&&price!==''){
            var _pa=document.createElement('span');_pa.textContent=_sym+price;_pa.style.cssText='font-size:1.6em;font-weight:700;color:#0f172a;';priceEl.appendChild(_pa);
            if(period){var _pb=document.createElement('span');_pb.textContent='/'+period;_pb.style.cssText='font-size:0.8em;color:#94a3b8;';priceEl.appendChild(_pb);}
          }
        }
        card.appendChild(priceEl);
        if(tier.description){var d=document.createElement('div');d.textContent=tier.description;d.style.cssText='font-size:0.78em;color:#64748b;margin-bottom:0.75rem;line-height:1.4;';card.appendChild(d);}
        if(tier.features&&tier.features.length){
          var ul=document.createElement('ul');ul.style.cssText='list-style:none;padding:0;margin:0 0 1rem;';
          tier.features.forEach(function(f){var li=document.createElement('li');li.textContent='✓ '+(f&&typeof f==='object'?f.text||'':f);li.style.cssText='font-size:0.78em;color:#475569;padding:0.2em 0;';ul.appendChild(li);});
          card.appendChild(ul);
        }
        if(tier.cta_type==='free_signup'){
          var ctaB=document.createElement('button');ctaB.textContent=tier.cta_label||'Get started for free';
          ctaB.style.cssText='display:block;width:100%;text-align:center;padding:0.6em;border-radius:0.4em;font-size:0.85em;font-weight:600;cursor:pointer;margin-top:auto;border:1px solid #e2e8f0;background:#fff;color:#475569;';
          ctaB.addEventListener('click',function(){window.location.hash='#/portal/signup/free';});
          card.appendChild(ctaB);
        }else if(tier.cta_url){
          var ctaA=document.createElement('a');ctaA.href=tier.cta_url;ctaA.target='_blank';ctaA.rel='noopener noreferrer';
          ctaA.textContent=tier.cta_label||'Get started';
          ctaA.style.cssText='display:block;text-align:center;padding:0.6em;border-radius:0.4em;font-size:0.85em;font-weight:600;text-decoration:none;margin-top:auto;'+(hl?'background:'+acc+';color:#fff;':'border:1px solid #e2e8f0;color:#475569;');
          card.appendChild(ctaA);
        }
        grid.appendChild(card);
      });
      modal.appendChild(grid);overlay.appendChild(modal);
    }
    render();
    overlay.addEventListener('click',function(e){if(e.target===overlay)close();});
    document.body.appendChild(overlay);
  }

  function lockMarker(marker,cfg){
    var root=getRoot(marker);
    var pivot=getPivot(marker,root);
    /* hide all following siblings immediately — before any async fetch */
    var sib=pivot.nextElementSibling;
    while(sib){
      if(!sib.hasAttribute('data-payglue-gate')){
        sib.style.display='none';
        sib.setAttribute('data-payglue-hidden','');
      }
      sib=sib.nextElementSibling;
    }
    /* insert gate card at content-root level, right after the HTML card */
    var card=buildCard(cfg);
    root.insertBefore(card,pivot.nextSibling);
  }

  var _unlocked=false;
  function unlock(){
    if(_unlocked)return;
    _unlocked=true;
    dbg('unlock: removing gate');
    document.querySelectorAll('[data-payglue-hidden]').forEach(function(el){
      el.style.display='';el.removeAttribute('data-payglue-hidden');
    });
    document.querySelectorAll('[data-payglue-gate]').forEach(function(el){el.remove();});
  }

  function hasAccess(member,productId){
    if(!member||!member.email){dbg('hasAccess: no member or email',member);return false;}
    var labels=member.labels||[];
    dbg('hasAccess: checking',labels.length,'labels for productId='+productId,labels);
    for(var i=0;i<labels.length;i++){
      var n=labels[i].name||labels[i].slug||'';
      if(n.indexOf('payglue-active:')===0){dbg('hasAccess: matched label',n);return true;}
      if(productId&&n==='payglue-active:'+productId){dbg('hasAccess: matched product label',n);return true;}
    }
    dbg('hasAccess: no matching label found');
    return false;
  }

  function loadConfig(configId,cb){
    fetch(API+'/api/v1/paywalls/'+encodeURIComponent(configId))
      .then(function(r){return r.ok?r.json():null;})
      .then(cb).catch(function(){cb(null);});
  }

  function injectStyles(){
    if(document.getElementById('payglue-styles'))return;
    var st=document.createElement('style');
    st.id='payglue-styles';
    st.textContent='[data-payglue-gate]{display:block!important;width:100%!important;box-sizing:border-box!important;font-size:18px!important}[data-payglue-headline]{display:block!important;margin:0 0 8px!important;font-size:26px!important;font-weight:700!important;color:#0f172a!important;line-height:1.25!important;font-family:inherit!important}[data-payglue-body]{display:block!important;margin:0 0 24px!important;font-size:18px!important;color:#64748b!important;line-height:1.6!important;font-family:inherit!important}';
    document.head.appendChild(st);
  }

  function run(){
    var markers=document.querySelectorAll('[data-payglue-gated]');
    if(!markers.length)return;
    injectStyles();

    /* For each marker: load config (by ID if available, else use inline attrs),
       lock immediately, then check member access. */
    var pending=markers.length;
    var memberResult=undefined; /* undefined = not yet fetched */
    var markerData=[]; /* [{marker, cfg, productId}] */

    function tryUnlock(){
      if(pending>0||memberResult===undefined)return;
      var allAccess=markerData.every(function(d){return hasAccess(memberResult,d.productId);});
      dbg('tryUnlock: allAccess='+allAccess,'pending='+pending,'markerCount='+markerData.length);
      if(allAccess)unlock();
    }

    markers.forEach(function(marker){
      var configId=marker.getAttribute('data-paywall-id')||'';
      var productId=marker.getAttribute('data-product-id')||'';
      var inlineCfg={
        headline:marker.getAttribute('data-headline'),
        body:marker.getAttribute('data-body'),
        button_text:marker.getAttribute('data-button-text'),
        button_url:marker.getAttribute('data-button-url'),
        button_color:marker.getAttribute('data-button-color'),
        product_id:productId,
      };

      function applyConfig(cfg){
        var merged=cfg||inlineCfg;
        var pid=merged.product_id||productId;
        lockMarker(marker,merged);
        markerData.push({marker:marker,cfg:merged,productId:pid});
        pending--;
        tryUnlock();
      }

      if(configId){
        loadConfig(configId,applyConfig);
      }else{
        applyConfig(null);
      }
    });

    /* fetch member from Ghost Portal, then verify access via PayGlue backend */
    dbg('fetching /members/api/member/');
    fetch('/members/api/member/',{credentials:'same-origin'})
      .then(function(r){dbg('member API status',r.status);return r.ok?r.json():null;})
      .then(function(m){
        dbg('member result',m);
        if(!m||!m.email){memberResult=null;tryUnlock();return;}
        /* Ghost Portal API doesn't return labels — verify via PayGlue backend */
        var checkUrl=API+'/t/'+org+'/api/v1/paywall/check?email='+encodeURIComponent(m.email);
        dbg('checking access',checkUrl);
        fetch(checkUrl)
          .then(function(r){return r.ok?r.json():null;})
          .then(function(d){
            dbg('access check result',d);
            /* If backend confirms active, fake a label on the member so hasAccess passes */
            if(d&&d.active){m.labels=[{name:'payglue-active:verified'}];}
            memberResult=m;tryUnlock();
          })
          .catch(function(e){dbg('access check error',e);memberResult=m;tryUnlock();});
      })
      .catch(function(e){dbg('member fetch error',e);memberResult=null;tryUnlock();});
  }

  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',run);}else{run();}
})();
"""


class PaywallConfigListView(APIView):
    """CRUD for saved paywall configs (per tenant)."""
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def get(self, request: Request, tenant_slug: str) -> Response:
        configs = PaywallConfig.objects.filter(tenant_slug=tenant_slug).order_by("-created_at")
        return Response([_serialize_paywall(c) for c in configs])

    def post(self, request: Request, tenant_slug: str) -> Response:
        limit_response = _enforce_resource_limit(tenant_slug, "paywalls")
        if limit_response is not None:
            return limit_response

        data = request.data
        cfg = PaywallConfig.objects.create(
            id=secrets.token_urlsafe(12),
            tenant_slug=tenant_slug,
            name=data.get("name") or "Untitled paywall",
            product_id=data.get("product_id", ""),
            product_name=data.get("product_name", ""),
            headline=data.get("headline") or "Premium content",
            body=data.get("body") or "Purchase access to continue reading.",
            button_text=data.get("button_text") or "Get access",
            button_url=data.get("button_url", ""),
            button_color=data.get("button_color") or "#4f46e5",
            text_color=data.get("text_color") or "#ffffff",
            border_radius=data.get("border_radius") or "md",
            width=data.get("width") or "auto",
            alignment=data.get("alignment") or "left",
        )
        return Response(_serialize_paywall(cfg), status=status.HTTP_201_CREATED)


class PaywallConfigDetailView(APIView):
    """Update or delete a single paywall config."""
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def _get_config(self, tenant_slug: str, config_id: str) -> PaywallConfig:
        try:
            return PaywallConfig.objects.get(id=config_id, tenant_slug=tenant_slug)
        except PaywallConfig.DoesNotExist:
            raise Http404

    def patch(self, request: Request, tenant_slug: str, config_id: str) -> Response:
        cfg = self._get_config(tenant_slug, config_id)
        data = request.data
        for field in ("name", "product_id", "product_name", "headline", "body", "button_text", "button_url", "button_color", "text_color", "border_radius", "width", "alignment"):
            if field in data:
                setattr(cfg, field, data[field])
        cfg.save()
        return Response(_serialize_paywall(cfg))

    def delete(self, request: Request, tenant_slug: str, config_id: str) -> Response:
        cfg = self._get_config(tenant_slug, config_id)
        cfg.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PaywallConfigPublicView(APIView):
    """Public endpoint: returns display config for a paywall ID (used by paywall.js)."""
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request, config_id: str) -> Response:
        try:
            cfg = PaywallConfig.objects.get(id=config_id)
        except PaywallConfig.DoesNotExist:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            "headline": cfg.headline,
            "body": cfg.body,
            "button_text": cfg.button_text,
            "button_url": cfg.button_url,
            "button_color": cfg.button_color,
            "text_color": getattr(cfg, "text_color", "#ffffff"),
            "border_radius": getattr(cfg, "border_radius", "md"),
            "width": getattr(cfg, "width", "auto"),
            "alignment": getattr(cfg, "alignment", "left"),
            "product_id": cfg.product_id,
        })


def _serialize_paywall(cfg: PaywallConfig) -> dict:
    return {
        "id": cfg.id,
        "name": cfg.name,
        "product_id": cfg.product_id,
        "product_name": cfg.product_name,
        "headline": cfg.headline,
        "body": cfg.body,
        "button_text": cfg.button_text,
        "button_url": cfg.button_url,
        "button_color": cfg.button_color,
        "text_color": getattr(cfg, "text_color", "#ffffff"),
        "border_radius": getattr(cfg, "border_radius", "md"),
        "width": getattr(cfg, "width", "auto"),
        "alignment": getattr(cfg, "alignment", "left"),
        "created_at": cfg.created_at.isoformat(),
        "updated_at": cfg.updated_at.isoformat(),
    }


class PaywallJsView(View):
    """Serves paywall.js — the public Ghost theme snippet."""

    def get(self, request):
        resp = DjangoHttpResponse(_PAYWALL_JS, content_type="application/javascript; charset=utf-8")
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Cache-Control"] = "public, max-age=300"
        return resp


_BUTTON_JS = r"""(function(){
  var s=document.currentScript;
  var buttonId=s&&s.getAttribute('data-id');
  if(!buttonId){console.warn('[PayGlue] data-id missing on button script');return;}
  var API='https://api.payglue.io';
  fetch(API+'/api/v1/buttons/'+encodeURIComponent(buttonId))
    .then(function(r){return r.ok?r.json():null;})
    .then(function(cfg){
      if(!cfg||!cfg.target_url)return;
      var align=cfg.alignment||'left';
      var justifyMap={left:'flex-start',center:'center',right:'flex-end'};
      var radiusMap={none:'0',md:'8px',full:'9999px'};
      var outer=document.createElement('div');
      outer.style.cssText='display:flex;flex-direction:column;align-items:'+justifyMap[align]+';margin:1rem 0;';
      var a=document.createElement('a');
      a.href=cfg.target_url;
      a.target=cfg.target||'_blank';
      a.rel=cfg.target==='_self'?'':'noopener noreferrer';
      a.textContent=cfg.label||'Buy now';
      var w=cfg.width==='full'?'100%':'auto';
      a.style.cssText='display:inline-block;background:'+(cfg.bg_color||'#4f46e5')+';color:'+(cfg.text_color||'#ffffff')+';padding:0.65em 1.75em;border-radius:'+(radiusMap[cfg.border_radius]||'8px')+';font-size:inherit;font-weight:600;text-decoration:none;width:'+w+';text-align:center;box-sizing:border-box;transition:opacity .15s;';
      a.onmouseover=function(){this.style.opacity='0.85';};
      a.onmouseout=function(){this.style.opacity='1';};
      outer.appendChild(a);
      if(cfg.description){
        var p=document.createElement('p');
        p.textContent=cfg.description;
        p.style.cssText='margin:0.5rem 0 0;font-size:inherit;color:#64748b;text-align:'+align+';';
        outer.appendChild(p);
      }
      s.parentNode.insertBefore(outer,s.nextSibling);
    })
    .catch(function(e){console.warn('[PayGlue] button load failed',e);});
})();
"""


class ButtonJsView(View):
    """Serves button.js — the public embeddable buy button snippet."""

    def get(self, request):
        resp = DjangoHttpResponse(_BUTTON_JS, content_type="application/javascript; charset=utf-8")
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Cache-Control"] = "public, max-age=300"
        return resp


class BuyButtonListView(APIView):
    """List and create buy buttons for a tenant."""
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def get(self, request: Request, tenant_slug: str) -> Response:
        buttons = BuyButton.objects.filter(tenant_slug=tenant_slug).order_by("-created_at")
        return Response([_serialize_button(b) for b in buttons])

    def post(self, request: Request, tenant_slug: str) -> Response:
        limit_response = _enforce_resource_limit(tenant_slug, "buy buttons")
        if limit_response is not None:
            return limit_response

        data = request.data
        btn = BuyButton.objects.create(
            id=secrets.token_urlsafe(12),
            tenant_slug=tenant_slug,
            name=data.get("name") or "Untitled button",
            label=data.get("label") or "Buy now",
            description=data.get("description", ""),
            target_url=data.get("target_url", ""),
            target=data.get("target") or "_blank",
            bg_color=data.get("bg_color") or "#4f46e5",
            text_color=data.get("text_color") or "#ffffff",
            border_radius=data.get("border_radius") or "md",
            width=data.get("width") or "auto",
            alignment=data.get("alignment") or "left",
            product_provider=data.get("product_provider", ""),
            product_id=data.get("product_id", ""),
        )
        return Response(_serialize_button(btn), status=status.HTTP_201_CREATED)


class BuyButtonDetailView(APIView):
    """Update or delete a single buy button."""
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def _get_button(self, tenant_slug: str, button_id: str) -> BuyButton:
        try:
            return BuyButton.objects.get(id=button_id, tenant_slug=tenant_slug)
        except BuyButton.DoesNotExist:
            raise Http404

    def patch(self, request: Request, tenant_slug: str, button_id: str) -> Response:
        btn = self._get_button(tenant_slug, button_id)
        for field in ("name", "label", "description", "target_url", "target", "bg_color", "text_color", "border_radius", "width", "alignment", "product_provider", "product_id"):
            if field in request.data:
                setattr(btn, field, request.data[field])
        btn.save()
        return Response(_serialize_button(btn))

    def delete(self, request: Request, tenant_slug: str, button_id: str) -> Response:
        btn = self._get_button(tenant_slug, button_id)
        btn.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BuyButtonPublicView(APIView):
    """Public endpoint: returns display config for a button ID (used by button.js)."""
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request, button_id: str) -> Response:
        try:
            btn = BuyButton.objects.get(id=button_id)
        except BuyButton.DoesNotExist:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        resp = Response({
            "label": btn.label,
            "description": btn.description,
            "target_url": btn.target_url,
            "target": btn.target,
            "bg_color": btn.bg_color,
            "text_color": btn.text_color,
            "border_radius": btn.border_radius,
            "width": btn.width,
            "alignment": btn.alignment,
        })
        resp["Access-Control-Allow-Origin"] = "*"
        return resp


def _serialize_button(btn: BuyButton) -> dict:
    return {
        "id": btn.id,
        "name": btn.name,
        "label": btn.label,
        "description": btn.description,
        "target_url": btn.target_url,
        "target": btn.target,
        "bg_color": btn.bg_color,
        "text_color": btn.text_color,
        "border_radius": btn.border_radius,
        "width": btn.width,
        "alignment": btn.alignment,
        "product_provider": btn.product_provider,
        "product_id": btn.product_id,
        "created_at": btn.created_at.isoformat(),
        "updated_at": btn.updated_at.isoformat(),
    }


class PaywallCheckView(APIView):
    """Public endpoint called by paywall.js to check member access."""
    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "paywall_check"

    def _cors_response(self, response: Response) -> Response:
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    def options(self, request: Request, tenant_slug: str) -> Response:
        return self._cors_response(Response(status=status.HTTP_204_NO_CONTENT))

    def get(self, request: Request, tenant_slug: str) -> Response:
        email = request.query_params.get("email", "").strip()
        if not email or "@" not in email:
            return self._cors_response(Response({"active": False, "error": "invalid_email"}))

        integration = IntegrationConfig.objects.filter(
            tenant_slug=tenant_slug, provider_key="cms", provider_type="ghost", enabled=True,
        ).first()
        if integration is None:
            return self._cors_response(Response({"active": False, "error": "not_configured"}))

        adapter = wiring.get_cms_adapter(integration.provider_type)
        tenant_ctx = TenantContext(tenant_slug=tenant_slug)
        try:
            result = adapter.paywall_check(email=email, tenant_ctx=tenant_ctx)
        except MissingCredentialsError:
            return self._cors_response(Response({"active": False, "error": "missing_credentials"}))
        except Exception:
            return self._cors_response(Response({"active": False, "error": "check_failed"}))

        return self._cors_response(Response(result))


class TenantAuditEventListView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> None:
        pass

    @staticmethod
    def _parse_datetime_filter(value: str, field_name: str):
        parsed = parse_datetime(value)
        if parsed is None:
            raise ValueError(f"{field_name} must be a valid ISO8601 datetime.")
        if timezone.is_naive(parsed):
            return timezone.make_aware(parsed)
        return parsed

    def get(self, request: Request, tenant_slug: str) -> Response:
        self._require_tenant_context(request, tenant_slug)
        events = PublicAuditEvent.objects.filter(tenant__slug=tenant_slug).order_by(
            "-created_at", "-id"
        )

        event_type = request.query_params.get("event_type")
        if event_type:
            events = events.filter(event_type=event_type)

        target_type = request.query_params.get("target_type")
        if target_type:
            events = events.filter(target_type=target_type)

        created_at_from = request.query_params.get("created_at_from")
        if created_at_from:
            try:
                events = events.filter(
                    created_at__gte=self._parse_datetime_filter(
                        created_at_from, "created_at_from"
                    )
                )
            except ValueError as exc:
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        created_at_to = request.query_params.get("created_at_to")
        if created_at_to:
            try:
                events = events.filter(
                    created_at__lte=self._parse_datetime_filter(
                        created_at_to, "created_at_to"
                    )
                )
            except ValueError as exc:
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = PublicAuditEventSerializer(events, many=True)
        return Response(serializer.data)


class TenantEventListView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> None:
        pass

    def get(self, request: Request, tenant_slug: str) -> Response:
        self._require_tenant_context(request, tenant_slug)
        events = WebhookInboundEvent.objects.filter(tenant_slug=tenant_slug).order_by(
            "-id"
        )
        serializer = WebhookInboundEventSerializer(events, many=True)
        return Response(serializer.data)




class TenantEventReplayView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    _REPLAYABLE_STATUSES = {
        WebhookInboundEvent.Status.FAILED,
        WebhookInboundEvent.Status.DEAD_LETTER,
        WebhookInboundEvent.Status.SKIPPED,
    }

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> None:
        pass

    def post(self, request: Request, tenant_slug: str, event_id: int) -> Response:
        self._require_tenant_context(request, tenant_slug)
        tenant = Tenant.objects.filter(slug=tenant_slug).only("id").first()
        with transaction.atomic():
            event = (
                WebhookInboundEvent.objects.select_for_update()
                .filter(
                    id=event_id,
                    tenant_slug=tenant_slug,
                )
                .first()
            )
            if event is None:
                return Response(
                    {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
                )

            if event.status not in self._REPLAYABLE_STATUSES:
                return Response(
                    {
                        "detail": "Only failed or dead_letter events can be replayed.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            event.status = WebhookInboundEvent.Status.RECEIVED
            event.attempts = 0
            event.next_attempt_at = None
            event.last_error = ""
            event.processing_started_at = None
            event.processed_at = None
            event.failed_at = None
            event.dead_lettered_at = None
            event.save(
                update_fields=[
                    "status",
                    "attempts",
                    "next_attempt_at",
                    "last_error",
                    "processing_started_at",
                    "processed_at",
                    "failed_at",
                    "dead_lettered_at",
                    "updated_at",
                ]
            )

        try:
            process_inbound_webhook_event.delay(
                event.id,
                ignore_timing=True,
                tenant_slug=tenant_slug,
                skip_verification=True,
            )
        except Exception:
            event.status = WebhookInboundEvent.Status.FAILED
            event.last_error = "queue publish failed"
            event.failed_at = timezone.now()
            event.save(
                update_fields=["status", "last_error", "failed_at", "updated_at"]
            )
            return Response(
                {"detail": "Webhook queue is unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if tenant is not None:
            write_public_audit_event(
                tenant=tenant,
                actor_membership=resolve_tenant_membership(request),
                event_type=PublicAuditEvent.EventType.EVENT_REPLAY_REQUESTED,
                target_type="webhook_event",
                target_id=str(event.id),
                metadata={"event_id": event.id, "provider": event.provider},
            )
        return Response(
            {"status": "accepted", "tracking_id": event.id},
            status=status.HTTP_202_ACCEPTED,
        )


# ---------------------------------------------------------------------------
# Pricing Table
# ---------------------------------------------------------------------------

_PRICING_TABLE_JS = r"""(function(){
  var s=document.currentScript;
  var tableId=s&&s.getAttribute('data-table-id');
  if(!tableId){console.warn('[PayGlue] data-table-id missing on pricing-table script');return;}
  var fullbleed=s&&s.getAttribute('data-fullbleed')==='true';
  var overlayLabel=s&&s.getAttribute('data-overlay-label');
  var overlayColor=(s&&s.getAttribute('data-overlay-color'))||'#4f46e5';
  var overlayRadius=(s&&s.getAttribute('data-overlay-radius'))||'md';
  var overlayAlign=(s&&s.getAttribute('data-overlay-align'))||'center';
  var API='https://api.payglue.io';
  fetch(API+'/api/v1/pricing-tables/'+encodeURIComponent(tableId)+'/public')
    .then(function(r){return r.ok?r.json():null;})
    .then(function(cfg){
      if(!cfg)return;
      if(overlayLabel!==null){
        /* ── Overlay trigger button mode ── */
        var radPx=overlayRadius==='full'?'9999px':overlayRadius==='none'?'0':'8px';
        var btn=document.createElement('button');
        btn.textContent=overlayLabel||'View plans';
        btn.style.cssText='display:inline-block;padding:12px 32px;background:'+overlayColor+';color:#fff;border:none;border-radius:'+radPx+';font-size:16px;font-weight:600;cursor:pointer;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;transition:opacity .15s;line-height:1.25;';
        btn.onmouseover=function(){btn.style.opacity='.85';};
        btn.onmouseout=function(){btn.style.opacity='1';};
        btn.addEventListener('click',function(){openOverlay(cfg);});
        var wrap=document.createElement('div');
        wrap.style.cssText='text-align:'+overlayAlign+';';
        wrap.appendChild(btn);
        s.parentNode.insertBefore(wrap,s.nextSibling);
      } else {
        /* ── Inline mode (always full-bleed) ── */
        var host=document.createElement('div');
        host.style.cssText='width:100vw;margin-left:calc(50% - 50vw);';
        var el=host.parentElement;
        while(el&&el!==document.body){
          var cs=window.getComputedStyle(el);
          if(cs.overflow==='hidden'||cs.overflowX==='hidden'){el.style.overflowX='visible';el.style.overflow='visible';}
          el=el.parentElement;
        }
        s.parentNode.insertBefore(host,s.nextSibling);
        var shadow=host.attachShadow?host.attachShadow({mode:'open'}):null;
        render(shadow||host,cfg);
      }
    })
    .catch(function(e){console.warn('[PayGlue] pricing table load failed',e);});

  function openOverlay(cfg){
    var overlay=document.createElement('div');
    overlay.style.cssText='position:fixed;top:0;left:0;width:100%;height:100%;z-index:99999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.55);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);padding:1rem;box-sizing:border-box;';
    var modal=document.createElement('div');
    modal.style.cssText='position:relative;background:#fff;border-radius:16px;width:100%;max-width:960px;max-height:90vh;overflow-y:auto;padding:1rem clamp(0.75rem,4vw,1.25rem) 1.75rem;box-sizing:border-box;box-shadow:0 25px 60px rgba(0,0,0,.3);';
    var hdr=document.createElement('div');
    hdr.style.cssText='display:flex;justify-content:flex-end;margin-bottom:.25rem;';
    var closeBtn=document.createElement('button');
    closeBtn.innerHTML='&times;';
    closeBtn.style.cssText='background:none;border:none;font-size:1.875rem;color:#94a3b8;cursor:pointer;line-height:1;padding:.25rem .625rem;border-radius:6px;transition:color .15s;';
    closeBtn.onmouseover=function(){closeBtn.style.color='#1e293b';};
    closeBtn.onmouseout=function(){closeBtn.style.color='#94a3b8';};
    function close(){if(document.body.contains(overlay))document.body.removeChild(overlay);}
    closeBtn.onclick=close;
    overlay.addEventListener('click',function(e){if(e.target===overlay)close();});
    document.addEventListener('keydown',function onEsc(e){if(e.key==='Escape'){close();document.removeEventListener('keydown',onEsc);}});
    hdr.appendChild(closeBtn);
    modal.appendChild(hdr);
    var tableHost=document.createElement('div');
    modal.appendChild(tableHost);
    var shadow=tableHost.attachShadow?tableHost.attachShadow({mode:'open'}):null;
    render(shadow||tableHost,cfg);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
  }

  function esc(v){return String(v||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

  function icon(i){
    if(i==='check')return '<span style="color:#22c55e;font-weight:700;line-height:1;">&#10003;</span>';
    if(i==='dot')return '<span style="color:#94a3b8;">&#8226;</span>';
    if(i==='dash')return '<span style="color:#cbd5e1;">&#8211;</span>';
    return '';
  }

  function render(container,cfg){
    var tiers=cfg.tiers||[];
    var tmpl=cfg.template||'classic';
    var showToggle=cfg.show_toggle||false;
    var yearly=false;

    function buildHTML(){
      var accent=cfg.accent_color||'#4f46e5';
      var css='*{box-sizing:border-box;}'
        +'.pg{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:16px;color:#1e293b;padding:24px clamp(12px,4vw,32px);max-width:1200px;margin-left:auto;margin-right:auto;}'
        +'.pg-tg{display:flex;align-items:center;justify-content:center;gap:12px;margin-bottom:32px;}'
        +'.pg-tl{font-size:16px;color:#94a3b8;cursor:pointer;transition:color .15s;}'
        +'.pg-tl.on{color:'+accent+';font-weight:600;}'
        +'.pg-tb{position:relative;width:44px;height:24px;border-radius:9999px;border:none;cursor:pointer;background:'+accent+';padding:0;transition:background .2s;}'
        +'.pg-tb.off{background:#e2e8f0;}'
        +'.knob{position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;transition:transform .2s;box-shadow:0 1px 3px rgba(0,0,0,.2);}'
        +'.pg-tb.on .knob{transform:translateX(20px);}'
        +'.pg-grid{display:grid;gap:20px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));}'
        +'.pg-card{border-radius:12px;padding:28px 24px;position:relative;border:1.5px solid #e2e8f0;background:#fff;display:flex;flex-direction:column;}'
        +'.pg-rb{position:absolute;top:-1px;left:50%;transform:translateX(-50%);background:'+accent+';color:#fff;font-size:11px;font-weight:700;padding:3px 12px;border-radius:0 0 8px 8px;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;}'
        +'.pg-n{font-size:18px;font-weight:700;margin:0 0 6px;}'
        +'.pg-d{font-size:15px;color:#64748b;margin:0 0 20px;line-height:1.5;flex:0 0 auto;}'
        +'.pg-p{font-size:32px;font-weight:800;line-height:1;margin:0 0 3px;}'
        +'.pg-p em{font-size:15px;font-weight:400;font-style:normal;color:#64748b;margin-left:2px;}'
        +'.pg-tr{font-size:13px;color:#64748b;margin:3px 0 16px;}'
        +'.pg-fl{list-style:none;padding:0;margin:16px 0 24px;display:flex;flex-direction:column;gap:8px;flex:1;}'
        +'.pg-fi{font-size:15px;display:flex;align-items:flex-start;gap:8px;line-height:1.5;}'
        +'.pg-fi-ic{min-width:16px;text-align:center;flex-shrink:0;}'
        +'.pg-cta{display:block;width:100%;padding:12px 16px;border-radius:8px;font-size:16px;font-weight:600;text-align:center;text-decoration:none;cursor:pointer;border:2px solid '+accent+';background:'+accent+';color:#fff;transition:opacity .15s;margin-top:auto;}'
        +'.pg-cta:hover{opacity:.85;}'
        +'button.pg-cta{-webkit-appearance:none;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:16px;font-weight:600;}';

      if(tmpl==='classic'){
        css+='.pg-card.hl{border-color:'+accent+';box-shadow:0 8px 32px rgba(79,70,229,.15);transform:translateY(-8px);}';
      } else if(tmpl==='bold'){
        css+='.pg-card.hl{background:'+accent+';border-color:'+accent+';color:#fff;}'
          +'.pg-card.hl .pg-d{color:rgba(255,255,255,.75);}'
          +'.pg-card.hl .pg-p em{color:rgba(255,255,255,.7);}'
          +'.pg-card.hl .pg-tr{color:rgba(255,255,255,.7);}'
          +'.pg-card.hl .pg-cta{background:#fff;color:'+accent+';border-color:#fff;}'
          +'.pg-card.hl .pg-rb{background:#fff;color:'+accent+';}';
      } else if(tmpl==='minimal'){
        css+='.pg-card{border-radius:0;border:none;border-top:2px solid #e2e8f0;padding:1.5rem 1rem;}'
          +'.pg-card.hl{border-top-color:'+accent+';}'
          +'.pg-cta{border-radius:4px;}';
      }

      var toggleHTML='';
      if(showToggle){
        toggleHTML='<div class="pg-tg">'
          +'<span class="pg-tl '+(yearly?'':'on')+'" data-t="monthly">Monthly</span>'
          +'<button class="pg-tb '+(yearly?'on':'off')+'" data-t="btn" aria-pressed="'+(yearly?'true':'false')+'"><span class="knob"></span></button>'
          +'<span class="pg-tl '+(yearly?'on':'')+'" data-t="yearly">Yearly</span>'
          +'</div>';
      }

      var SYMS={'EUR':'€','USD':'$','GBP':'£','CHF':'CHF '};
      var sym=SYMS[cfg.currency||'EUR']||'€';
      var tiersHTML=tiers.map(function(t){
        var rawPrice=yearly?(t.price_yearly||t.price_monthly||''):(t.price_monthly||'');
        var price=rawPrice!==''?(sym+rawPrice):'';
        var period=(showToggle&&t.cta_type!=='one_time'&&t.cta_type!=='free_signup')?(yearly?' / yr':' / mo'):'';
        var cc='pg-card'+(t.highlight?' hl':'');
        var rb=(t.highlight&&t.ribbon_text)?'<div class="pg-rb">'+esc(t.ribbon_text)+'</div>':'';
        var trial=t.trial_days?'<div class="pg-tr">'+esc(t.trial_days)+'-day free trial</div>':'';
        var feats=(t.features||[]).map(function(f){
          return '<li class="pg-fi"><span class="pg-fi-ic">'+icon(f.icon)+'</span><span>'+esc(f.text)+'</span></li>';
        }).join('');
        var cta=t.cta_type==='free_signup'
          ?'<button class="pg-cta" data-pg-signup="true">'+esc(t.cta_label||'Get started for free')+'</button>'
          :t.cta_url
            ?'<a class="pg-cta" href="'+esc(t.cta_url)+'" target="_blank" rel="noopener noreferrer">'+esc(t.cta_label||'Get started')+'</a>'
            :'<span class="pg-cta">'+esc(t.cta_label||'Get started')+'</span>';
        return '<div class="'+esc(cc)+'">'+rb+'<div class="pg-n">'+esc(t.name)+'</div><div class="pg-d">'+esc(t.description)+'</div><div class="pg-p">'+esc(price)+'<em>'+esc(period)+'</em></div>'+trial+'<ul class="pg-fl">'+feats+'</ul>'+cta+'</div>';
      }).join('');

      return '<style>'+css+'</style><div class="pg">'+toggleHTML+'<div class="pg-grid">'+tiersHTML+'</div></div>';
    }

    container.innerHTML=buildHTML();

    container.addEventListener('click',function(e){
      if(showToggle){
        var tog=e.target.closest?e.target.closest('[data-t]'):null;
        if(tog){
          var action=tog.getAttribute('data-t');
          if(action==='monthly')yearly=false;
          else if(action==='yearly')yearly=true;
          else yearly=!yearly;
          container.innerHTML=buildHTML();
          return;
        }
      }
      var btn=e.target.closest?e.target.closest('[data-pg-signup]'):null;
      if(btn){window.location.hash='#/portal/signup/free';}
    });
  }
})();
"""


def _serialize_pricing_table(table: PricingTable) -> dict:
    tiers = list(table.tiers.all())
    return {
        "id": table.id,
        "name": table.name,
        "template": table.template,
        "show_toggle": table.show_toggle,
        "accent_color": table.accent_color,
        "currency": table.currency,
        "tiers": [_serialize_pricing_tier(t) for t in tiers],
        "created_at": table.created_at.isoformat(),
        "updated_at": table.updated_at.isoformat(),
    }


def _serialize_pricing_tier(tier: PricingTier) -> dict:
    return {
        "id": tier.id,
        "position": tier.position,
        "name": tier.name,
        "description": tier.description,
        "price_monthly": tier.price_monthly,
        "price_yearly": tier.price_yearly,
        "trial_days": tier.trial_days,
        "highlight": tier.highlight,
        "ribbon_text": tier.ribbon_text,
        "cta_type": tier.cta_type,
        "cta_label": tier.cta_label,
        "cta_url": tier.cta_url,
        "features": tier.features,
        "product_provider": tier.product_provider,
        "product_id": tier.product_id,
    }


def _replace_tiers(table: PricingTable, tiers_data: list) -> None:
    table.tiers.all().delete()
    for i, td in enumerate(tiers_data):
        PricingTier.objects.create(
            id=secrets.token_urlsafe(12),
            table=table,
            position=i,
            name=td.get("name") or "Tier",
            description=td.get("description", ""),
            price_monthly=td.get("price_monthly", ""),
            price_yearly=td.get("price_yearly", ""),
            trial_days=td.get("trial_days") or None,
            highlight=bool(td.get("highlight", False)),
            ribbon_text=(td.get("ribbon_text") or "")[:10],
            cta_type=td.get("cta_type") or "custom_url",
            cta_label=td.get("cta_label") or "Get started",
            cta_url=td.get("cta_url", ""),
            features=td.get("features") or [],
            product_provider=td.get("product_provider") or "",
            product_id=td.get("product_id") or "",
        )


class PricingTableJsView(View):
    def get(self, request):
        resp = DjangoHttpResponse(_PRICING_TABLE_JS, content_type="application/javascript; charset=utf-8")
        resp["Access-Control-Allow-Origin"] = "*"
        resp["Cache-Control"] = "public, max-age=300"
        return resp


class PricingTableListView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def get(self, request: Request, tenant_slug: str) -> Response:
        tables = PricingTable.objects.filter(tenant_slug=tenant_slug).order_by("-created_at")
        return Response([_serialize_pricing_table(t) for t in tables])

    def post(self, request: Request, tenant_slug: str) -> Response:
        limit_response = _enforce_resource_limit(tenant_slug, "pricing tables")
        if limit_response is not None:
            return limit_response

        data = request.data
        table = PricingTable.objects.create(
            id=secrets.token_urlsafe(12),
            tenant_slug=tenant_slug,
            name=data.get("name") or "Untitled table",
            template=data.get("template") or "classic",
            show_toggle=bool(data.get("show_toggle", False)),
            accent_color=data.get("accent_color") or "#4f46e5",
            currency=data.get("currency") or "EUR",
        )
        if "tiers" in data and isinstance(data["tiers"], list):
            _replace_tiers(table, data["tiers"])
        return Response(_serialize_pricing_table(table), status=status.HTTP_201_CREATED)


class PricingTableDetailView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def _get_table(self, tenant_slug: str, table_id: str) -> PricingTable:
        try:
            return PricingTable.objects.get(id=table_id, tenant_slug=tenant_slug)
        except PricingTable.DoesNotExist:
            raise Http404

    def patch(self, request: Request, tenant_slug: str, table_id: str) -> Response:
        table = self._get_table(tenant_slug, table_id)
        for field in ("name", "template", "show_toggle", "accent_color", "currency"):
            if field in request.data:
                setattr(table, field, request.data[field])
        table.save()
        if "tiers" in request.data and isinstance(request.data["tiers"], list):
            _replace_tiers(table, request.data["tiers"])
        return Response(_serialize_pricing_table(table))

    def delete(self, request: Request, tenant_slug: str, table_id: str) -> Response:
        table = self._get_table(tenant_slug, table_id)
        table.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PricingTablePublicView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request, table_id: str) -> Response:
        try:
            table = PricingTable.objects.get(id=table_id)
        except PricingTable.DoesNotExist:
            return Response({"error": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        resp = Response({
            "id": table.id,
            "template": table.template,
            "show_toggle": table.show_toggle,
            "accent_color": table.accent_color,
            "currency": table.currency,
            "tiers": [_serialize_pricing_tier(t) for t in table.tiers.all()],
        })
        resp["Access-Control-Allow-Origin"] = "*"
        return resp


class TenantMappingTestView(APIView):
    """PG-202: fire a synthetic event for one mapping at a test email through
    the real resolve + Ghost-apply pipeline, so a creator can verify a
    connection end to end without a real purchase. Owner/Admin only."""

    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [TenantReadOwnerAdminWrite]

    def post(self, request: Request, tenant_slug: str, mapping_id: int) -> Response:
        try:
            mapping = ProductMapping.objects.get(id=mapping_id, tenant_slug=tenant_slug)
        except ProductMapping.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        test_email = (request.data.get("test_email") or "").strip()
        try:
            validate_email(test_email)
        except ValidationError:
            return Response(
                {"detail": "A valid test_email is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = run_mapping_test(mapping, test_email)

        tenant = Tenant.objects.filter(slug=tenant_slug).only("id").first()
        if tenant is not None:
            write_public_audit_event(
                tenant=tenant,
                actor_membership=resolve_tenant_membership(request),
                event_type=PublicAuditEvent.EventType.TEST_EVENT_SENT,
                target_type="product_mapping",
                target_id=str(mapping.id),
                metadata={
                    "provider": mapping.payment_provider,
                    "event_type": mapping.event_type,
                    "ok": result["ok"],
                },
            )

        return Response(result, status=status.HTTP_200_OK)

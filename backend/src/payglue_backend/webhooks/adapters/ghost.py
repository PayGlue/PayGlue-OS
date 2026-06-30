# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib import error, request
from urllib.parse import urlparse

from payglue_backend.core.errors import (
    CmsApplyEntitlementError,
    MissingCredentialsError,
)
from payglue_backend.core.interfaces import CredentialProvider
from payglue_backend.core.models import CanonicalCustomer, EntitlementInstruction, TenantContext

logger = logging.getLogger(__name__)


class HttpResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class HttpApiClient(Protocol):
    def post(
        self, url: str, json_body: dict[str, object], headers: dict[str, str]
    ) -> HttpResponse: ...

    def put(
        self, url: str, json_body: dict[str, object], headers: dict[str, str]
    ) -> HttpResponse: ...

    def get(self, url: str, headers: dict[str, str]) -> HttpResponse: ...


class UrllibHttpApiClient:
    def post(
        self, url: str, json_body: dict[str, object], headers: dict[str, str]
    ) -> HttpResponse:
        body = json.dumps(json_body).encode("utf-8")
        req = request.Request(url=url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=5) as response:
                payload = response.read().decode("utf-8")
                return HttpResponse(status_code=response.status, text=payload)
        except error.HTTPError as exc:
            payload = exc.read().decode("utf-8") if exc.fp else ""
            return HttpResponse(status_code=exc.code, text=payload)

    def put(
        self, url: str, json_body: dict[str, object], headers: dict[str, str]
    ) -> HttpResponse:
        body = json.dumps(json_body).encode("utf-8")
        req = request.Request(url=url, data=body, headers=headers, method="PUT")
        try:
            with request.urlopen(req, timeout=5) as response:
                payload = response.read().decode("utf-8")
                return HttpResponse(status_code=response.status, text=payload)
        except error.HTTPError as exc:
            payload = exc.read().decode("utf-8") if exc.fp else ""
            return HttpResponse(status_code=exc.code, text=payload)

    def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        req = request.Request(url=url, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=5) as response:
                payload = response.read().decode("utf-8")
                return HttpResponse(status_code=response.status, text=payload)
        except error.HTTPError as exc:
            payload = exc.read().decode("utf-8") if exc.fp else ""
            return HttpResponse(status_code=exc.code, text=payload)


def _slugify(value: str) -> str:
    normalized = re.sub(r"[._\s]+", "-", value.lower().strip())
    return re.sub(r"[^a-z0-9-]", "", normalized).strip("-")


class GhostCmsAdapter:
    def __init__(
        self,
        http_client: HttpApiClient,
        credential_provider: CredentialProvider,
        provider_key: str = "ghost",
    ) -> None:
        self._http_client = http_client
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._jwt_ttl = timedelta(minutes=5)

    @staticmethod
    def _validate_base_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise MissingCredentialsError(
                tenant_slug="", provider_key="ghost", missing_fields=("api_base_url",)
            )
        hostname = parsed.hostname or ""
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                raise MissingCredentialsError(
                    tenant_slug="", provider_key="ghost", missing_fields=("api_base_url",)
                )
        except ValueError:
            lower = hostname.lower()
            if lower in ("localhost", "localhost.localdomain") or lower.endswith(".internal") or lower.endswith(".local"):
                raise MissingCredentialsError(
                    tenant_slug="", provider_key="ghost", missing_fields=("api_base_url",)
                )

    def apply_entitlement(
        self,
        customer: CanonicalCustomer,
        instruction: EntitlementInstruction,
        tenant_ctx: TenantContext,
    ) -> None:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        base_url = credentials.get("api_base_url")
        api_key = credentials.get("admin_api_key")
        if not base_url or not api_key:
            missing_fields: list[str] = []
            if not base_url:
                missing_fields.append("api_base_url")
            if not api_key:
                missing_fields.append("admin_api_key")
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=tuple(missing_fields),
            )

        self._validate_base_url(base_url)
        email = customer.email
        if not email:
            raise CmsApplyEntitlementError("customer email is required for Ghost member sync")

        auth_token = self._build_admin_jwt(api_key)
        headers = {
            "Authorization": f"Ghost {auth_token}",
            "Accept-Version": "v5.0",
            "Content-Type": "application/json",
        }

        admin_base = base_url.rstrip("/")
        members_url = f"{admin_base}/ghost/api/admin/members/"

        # Check if Stripe is connected in Ghost to decide between comped vs free+label.
        try:
            stripe_result = self.stripe_status(tenant_ctx)
            stripe_connected = bool(stripe_result.get("connected"))
        except Exception:
            stripe_connected = False

        is_grant = instruction.action == "grant"
        comped = stripe_connected and is_grant

        meta = instruction.metadata or {}
        subscribed = meta.get("ghost_subscribed", True)
        # Support both old single string and new array format.
        raw_types = meta.get("ghost_email_types") or (
            [meta["ghost_email_type"]] if meta.get("ghost_email_type") else []
        )
        email_types: list[str] = [t for t in raw_types if t]
        extra_labels: list[str] = meta.get("ghost_labels", []) or []

        labels = [
            {"name": "source:payglue"},
            {"name": f"product:{_slugify(instruction.entitlement_key)}"},
        ] + [{"name": lbl} for lbl in extra_labels if lbl]
        # Without Stripe, track access via label so the JS paywall can verify it.
        if not stripe_connected and is_grant:
            provider_slug = _slugify(meta.get("_provider", "payglue"))
            labels.append({"name": f"payglue-active:{provider_slug}"})
        provider = meta.get("_provider", "payglue")
        product_id = meta.get("_product_id", instruction.entitlement_key)
        event_id = meta.get("_event_id", "")
        note_lines = [f"Direct via PayGlue | Provider: {provider}", f"Product: {product_id}"]
        if event_id:
            note_lines.append(f"Order: {event_id}")
        note = "\n".join(note_lines)

        member_id = self._find_member_id(members_url, email, headers)

        try:
            if member_id is None:
                member_data: dict[str, object] = {
                    "email": email,
                    "labels": labels,
                    "note": note,
                    "subscribed": subscribed,
                    "comped": comped,
                }
                if customer.name:
                    member_data["name"] = customer.name
                # send_email and email_type must be query parameters, not body fields (Ghost Admin API).
                post_body: dict[str, object] = {"members": [member_data]}
                logger.info(
                    "ghost create member email=%s email_types=%r",
                    email,
                    email_types,
                )
                for i, email_type in enumerate(email_types):
                    url_with_params = f"{members_url}?send_email=true&email_type={email_type}"
                    if i == 0:
                        response = self._http_client.post(
                            url=url_with_params,
                            json_body=post_body,
                            headers=headers,
                        )
                        logger.info("ghost create member response status=%s body=%.500s", response.status_code, response.text)
                        if response.status_code >= 400:
                            raise CmsApplyEntitlementError(
                                f"ghost returned status {response.status_code}: {response.text[:300]}"
                            )
                        try:
                            created_id = json.loads(response.text)["members"][0]["id"]
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            created_id = None
                    elif created_id:
                        member_url_with_params = f"{members_url}{created_id}/?send_email=true&email_type={email_type}"
                        logger.info("ghost send extra email type=%s member_id=%s", email_type, created_id)
                        self._http_client.put(
                            url=member_url_with_params,
                            json_body={"members": [{}]},
                            headers=headers,
                        )
                if not email_types:
                    response = self._http_client.post(
                        url=members_url,
                        json_body=post_body,
                        headers=headers,
                    )
                    if response.status_code >= 400:
                        raise CmsApplyEntitlementError(
                            f"ghost returned status {response.status_code}: {response.text[:300]}"
                        )
                return
            else:
                logger.info("ghost update existing member id=%s email=%s", member_id, email)
                response = self._http_client.put(
                    url=f"{members_url}{member_id}/",
                    json_body={"members": [{"comped": comped, "labels": labels}]},
                    headers=headers,
                )
                logger.info("ghost update member response status=%s", response.status_code)
        except CmsApplyEntitlementError:
            raise
        except Exception as exc:
            raise CmsApplyEntitlementError("ghost request failed") from exc

        if response.status_code >= 400:
            raise CmsApplyEntitlementError(
                f"ghost returned status {response.status_code}"
            )

    def _find_member_id(
        self, members_url: str, email: str, headers: dict[str, str]
    ) -> str | None:
        safe_email = email.replace("'", "%27")
        lookup_url = f"{members_url}?filter=email:'{safe_email}'"
        try:
            response = self._http_client.get(url=lookup_url, headers=headers)
        except Exception as exc:
            raise CmsApplyEntitlementError("ghost member lookup failed") from exc

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise CmsApplyEntitlementError(
                f"ghost member lookup returned status {response.status_code}"
            )

        try:
            data = json.loads(response.text)
            members = data.get("members", [])
            if isinstance(members, list) and members:
                member_id = members[0].get("id")
                return str(member_id) if member_id else None
        except (json.JSONDecodeError, AttributeError):
            pass

        return None

    def health_check(self, tenant_ctx: TenantContext) -> dict[str, object]:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        base_url = credentials.get("api_base_url")
        api_key = credentials.get("admin_api_key")
        if not base_url or not api_key:
            missing_fields: list[str] = []
            if not base_url:
                missing_fields.append("api_base_url")
            if not api_key:
                missing_fields.append("admin_api_key")
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=tuple(missing_fields),
            )

        self._validate_base_url(base_url)
        url = f"{base_url.rstrip('/')}/ghost/api/admin/site/"
        auth_token = self._build_admin_jwt(api_key)
        headers = {
            "Authorization": f"Ghost {auth_token}",
            "Accept-Version": "v5.0",
        }

        try:
            response = self._http_client.get(url=url, headers=headers)
        except Exception:
            return {
                "ok": False,
                "code": "transport_error",
                "message": "Ghost health check request failed.",
            }

        if response.status_code >= 400:
            return {
                "ok": False,
                "code": f"http_{response.status_code}",
                "message": f"Ghost health check returned status {response.status_code}.",
            }

        return {
            "ok": True,
            "code": "ok",
            "message": "Ghost health check succeeded.",
        }

    def stripe_status(self, tenant_ctx: TenantContext) -> dict[str, object]:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        base_url = credentials.get("api_base_url")
        api_key = credentials.get("admin_api_key")
        if not base_url or not api_key:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("api_base_url", "admin_api_key"),
            )

        self._validate_base_url(base_url)
        url = f"{base_url.rstrip('/')}/ghost/api/admin/settings/"
        auth_token = self._build_admin_jwt(api_key)
        headers = {"Authorization": f"Ghost {auth_token}", "Accept-Version": "v5.0"}

        try:
            response = self._http_client.get(url=url, headers=headers)
        except Exception:
            return {"connected": False, "error": "request_failed"}

        if response.status_code >= 400:
            return {"connected": False, "error": f"http_{response.status_code}"}

        try:
            settings_list = json.loads(response.text).get("settings", [])
            settings = {s["key"]: s["value"] for s in settings_list}
        except (json.JSONDecodeError, KeyError, TypeError):
            return {"connected": False, "error": "parse_error"}

        account_id = settings.get("stripe_connect_account_id")
        display_name = settings.get("stripe_connect_display_name") or None
        return {
            "connected": bool(account_id),
            "display_name": display_name,
        }

    def paywall_check(self, email: str, tenant_ctx: TenantContext) -> dict[str, object]:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        base_url = credentials.get("api_base_url")
        api_key = credentials.get("admin_api_key")
        if not base_url or not api_key:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("api_base_url", "admin_api_key"),
            )

        auth_token = self._build_admin_jwt(api_key)
        headers = {"Authorization": f"Ghost {auth_token}", "Accept-Version": "v5.0"}
        self._validate_base_url(base_url)
        safe_email = email.replace("'", "%27")
        url = f"{base_url.rstrip('/')}/ghost/api/admin/members/?filter=email:'{safe_email}'&include=labels"

        try:
            response = self._http_client.get(url=url, headers=headers)
        except Exception:
            return {"active": False, "error": "request_failed"}

        if response.status_code >= 400:
            return {"active": False, "error": f"http_{response.status_code}"}

        try:
            members = json.loads(response.text).get("members", [])
        except (json.JSONDecodeError, KeyError, TypeError):
            return {"active": False, "error": "parse_error"}

        if not members:
            return {"active": False}

        member = members[0]
        if member.get("comped"):
            return {"active": True, "type": "subscription"}

        for label in member.get("labels", []):
            if str(label.get("name", "")).startswith("payglue-active:"):
                return {"active": True, "type": "one_time"}

        return {"active": False}

    def _build_admin_jwt(self, admin_api_key: str) -> str:
        key_id, _, secret_hex = admin_api_key.partition(":")
        if not key_id or not secret_hex:
            raise CmsApplyEntitlementError("ghost admin_api_key format is invalid")

        try:
            secret = bytes.fromhex(secret_hex)
        except ValueError as exc:
            raise CmsApplyEntitlementError(
                "ghost admin_api_key secret is not hex"
            ) from exc

        now = datetime.now(tz=UTC)
        payload = {
            "iat": int(now.timestamp()),
            "exp": int((now + self._jwt_ttl).timestamp()),
            "aud": "/admin/",
        }
        header = {"alg": "HS256", "kid": key_id, "typ": "JWT"}

        encoded_header = self._encode_jwt_part(header)
        encoded_payload = self._encode_jwt_part(payload)
        signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
        signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
        encoded_signature = (
            base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        )
        return f"{encoded_header}.{encoded_payload}.{encoded_signature}"

    @staticmethod
    def _encode_jwt_part(payload: Mapping[str, object]) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

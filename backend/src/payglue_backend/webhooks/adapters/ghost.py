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
from urllib.parse import urlparse, quote

from payglue_backend.core.errors import (
    CmsApplyEntitlementError,
    MissingCredentialsError,
)
from payglue_backend.core.interfaces import CredentialProvider
from payglue_backend.core.models import CanonicalCustomer, EntitlementInstruction, TenantContext

logger = logging.getLogger(__name__)

# Ghost rejects a member note longer than this.
_NOTE_MAX_CHARS = 500


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

    def delete(self, url: str, headers: dict[str, str]) -> HttpResponse: ...


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

    def delete(self, url: str, headers: dict[str, str]) -> HttpResponse:
        req = request.Request(url=url, headers=headers, method="DELETE")
        try:
            with request.urlopen(req, timeout=5) as response:
                payload = response.read().decode("utf-8")
                return HttpResponse(status_code=response.status, text=payload)
        except error.HTTPError as exc:
            payload = exc.read().decode("utf-8") if exc.fp else ""
            return HttpResponse(status_code=exc.code, text=payload)


# The label a sandbox or test-mode purchase leaves on the Ghost member. The
# retention job selects by it, so it must not change without a migration of
# existing members.
TEST_LABEL = "payglue-test"


# Ghost's own list (isActiveSubscriptionStatus): a subscription in one of these
# still grants access, so a complimentary one in this state is what to cancel.
ACTIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing", "unpaid", "past_due"})


def _filter_value(value: str) -> str:
    """A value for Ghost's `filter=` query parameter, percent-encoded in full.
    The filter travels in the URL, so a "+" that is left as it is arrives at
    Ghost as a space and the lookup for an address like name+tag@example.com
    finds nothing. The quote is encoded too, so it cannot close the filter
    string early."""
    return quote(value, safe="")


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
        # PG-325: a sandbox or test-mode purchase is marked with a label, and
        # that is all. The newsletter and the emails follow the rule like for a
        # real purchase, because a test is there to show what the rule does.
        # The label is what a filter, and the operator's retention job, use.
        is_test = bool(meta.get("_is_test"))

        labels = [
            {"name": "source:payglue"},
            {"name": f"product:{_slugify(instruction.entitlement_key)}"},
        ] + [{"name": lbl} for lbl in extra_labels if lbl]
        # PG-229: status and provider are two facts, so they are two labels.
        # Carrying both in one string (payglue-active:polar) forced every reader
        # to prefix-match, and that is how the paywall ended up with an
        # unreachable branch comparing the provider against a product id.
        #
        # Written on every grant, not only when Ghost has no Stripe account.
        # The stripe_connected lookup above is a network call that falls back to
        # False when it fails, so tying the label to it made the member's state
        # depend on whether an unrelated request succeeded.
        # PG-271: the status label is written in both directions. Leaving the
        # member with no status at all made a cancellation, a grant that never
        # ran and a never-customer look identical, which is exactly the question
        # someone asks months later. The provider label used to hang off the
        # grant branch and disappeared with the status, taking the one fact that
        # says who took the money.
        labels.append({"name": "payglue-active" if is_grant else "payglue-ended"})
        labels.append({"name": f"payglue-provider:{_slugify(meta.get('_provider', 'payglue'))}"})
        if is_test:
            labels.append({"name": TEST_LABEL})
        provider = meta.get("_provider", "payglue")
        product_id = meta.get("_product_id", instruction.entitlement_key)
        event_id = meta.get("_event_id", "")
        note_lines = [f"Direct via PayGlue | Provider: {provider}", f"Product: {product_id}"]
        if is_test:
            note_lines.append("Test purchase (provider sandbox or test mode)")
        order = self._stamped_line("Order", meta.get("_occurred_at"), event_id)
        if order:
            note_lines.append(order)
        note = "\n".join(note_lines)

        found = self._find_member(members_url, email, headers)
        member_id = str(found["id"]) if found and found.get("id") else None
        existing_note = str(found.get("note") or "") if found else ""
        if not is_grant:
            if member_id is None:
                # Creating a member here would invent a cancellation for someone
                # who never bought anything. Reachable through the
                # revoke-everything path for providers that do not name the tier
                # on a cancellation.
                logger.info("ghost revoke skipped, no member for email=%s", email)
                return
            # An ending adds a line, it does not replace the purchase note. What
            # was bought and under which order stays readable, which is the
            # whole point of looking at a cancelled member months later.
            note = self._with_ended_line(existing_note or note, meta.get("_occurred_at"), event_id)

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
                    # The note travels with the update from PG-271 on. Without
                    # it an ending had nowhere to record its date, and a repeat
                    # purchase left the previous ending standing as a lie.
                    json_body={"members": [{"comped": comped, "labels": labels, "note": note}]},
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

        if not is_grant and stripe_connected and member_id is not None:
            self._end_complimentary_access(members_url, member_id, headers)

    def _end_complimentary_access(
        self, members_url: str, member_id: str, headers: dict[str, str]
    ) -> None:
        """Cancel the Complimentary subscription that `comped: true` created.

        With Stripe connected, Ghost expresses a comped member as a zero-amount
        Stripe subscription whose price is nicknamed "Complimentary". Sending
        `comped: false` is meant to cancel it, but Ghost's member edit only
        loads the labels relation, so its check for an existing complimentary
        subscription comes back empty and the subscription stays. Verified on
        Ghost 6.68. The member then keeps the tier, keeps `status: comped`, and
        the paywall keeps letting them in. So after the edit we read the member
        back and cancel every active complimentary subscription ourselves,
        through the same Admin API endpoint the Ghost admin uses. Ghost syncs
        the member's status and tier off the cancelled subscription.

        A member with no active complimentary subscription left (Ghost did
        cancel it, or the comp was never Stripe-backed) needs nothing here.
        """
        member = self._get_member(members_url, member_id, headers)
        subscriptions = member.get("subscriptions") or []
        if not isinstance(subscriptions, list):
            return
        for subscription in subscriptions:
            if not isinstance(subscription, dict):
                continue
            if subscription.get("status") not in ACTIVE_SUBSCRIPTION_STATUSES:
                continue
            nickname = (
                (subscription.get("price") or {}).get("nickname")
                or (subscription.get("plan") or {}).get("nickname")
                or ""
            )
            if str(nickname).lower() != "complimentary":
                continue
            subscription_id = subscription.get("id")
            if not subscription_id:
                continue
            logger.info(
                "ghost cancel complimentary subscription member_id=%s subscription_id=%s",
                member_id,
                subscription_id,
            )
            try:
                response = self._http_client.put(
                    url=f"{members_url}{member_id}/subscriptions/{subscription_id}/",
                    json_body={"cancel_at_period_end": True, "status": "canceled"},
                    headers=headers,
                )
            except Exception as exc:
                raise CmsApplyEntitlementError("ghost subscription cancel failed") from exc
            if response.status_code >= 400:
                raise CmsApplyEntitlementError(
                    f"ghost subscription cancel returned status {response.status_code}: {response.text[:300]}"
                )

    def _get_member(
        self, members_url: str, member_id: str, headers: dict[str, str]
    ) -> dict[str, object]:
        try:
            response = self._http_client.get(url=f"{members_url}{member_id}/", headers=headers)
        except Exception as exc:
            raise CmsApplyEntitlementError("ghost member read failed") from exc
        if response.status_code >= 400:
            raise CmsApplyEntitlementError(
                f"ghost member read returned status {response.status_code}"
            )
        try:
            members = json.loads(response.text).get("members", [])
        except (json.JSONDecodeError, AttributeError):
            return {}
        if isinstance(members, list) and members and isinstance(members[0], dict):
            return members[0]
        return {}

    @staticmethod
    def _stamped_line(label: str, occurred_at: object, event_id: str) -> str:
        """One note line: what happened, when, and which event says so. Both the
        date and the id are optional. Events queued before the date shipped carry
        none, and the newsletter path builds its instructions without one."""
        date = str(occurred_at or "")[:10]
        parts = [f"{label}: {date}" if date else label]
        if event_id:
            parts.append(f"Event: {event_id}")
        if len(parts) == 1 and not date:
            return ""
        return " | ".join(parts)

    @classmethod
    def _with_ended_line(cls, note: str, occurred_at: object, event_id: str) -> str:
        """Add the end date under the purchase lines, replacing an earlier one
        rather than stacking."""
        ended = cls._stamped_line("Ended", occurred_at, event_id) or "Ended"

        kept = [line for line in note.splitlines() if line and not line.startswith("Ended")]
        # Ghost caps the note at 500 characters. The end date is the newest fact,
        # so it displaces the oldest line instead of pushing the write over.
        while kept and len("\n".join([*kept, ended])) > _NOTE_MAX_CHARS:
            kept.pop(0)
        return "\n".join([*kept, ended])[:_NOTE_MAX_CHARS]

    def _find_member(
        self, members_url: str, email: str, headers: dict[str, str]
    ) -> dict[str, object] | None:
        """The member with this email as Ghost returns it, or None."""
        lookup_url = f"{members_url}?filter=email:'{_filter_value(email)}'"
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
            if isinstance(members, list) and members and isinstance(members[0], dict):
                if members[0].get("id"):
                    return members[0]
        except (json.JSONDecodeError, AttributeError):
            pass

        return None

    def purge_test_members(self, tenant_ctx: TenantContext, older_than_days: int) -> dict[str, int]:
        """PG-325: delete members that carry the test label and were created
        more than `older_than_days` ago. Only the label decides; a real member
        never carries it, because it is written from the provider's own
        sandbox flag. Returns how many were deleted and how many failed."""
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
        headers = {
            "Authorization": f"Ghost {self._build_admin_jwt(api_key)}",
            "Accept-Version": "v5.0",
        }
        members_url = f"{base_url.rstrip('/')}/ghost/api/admin/members/"
        cutoff = (datetime.now(tz=UTC) - timedelta(days=max(int(older_than_days), 1))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        member_filter = quote(f"label:{TEST_LABEL}+created_at:<'{cutoff}'", safe="")
        deleted = failed = 0
        # Ghost pages at 100 by default; deleting shifts the pages, so the
        # first page is fetched again until it comes back empty.
        for _ in range(50):
            response = self._http_client.get(
                url=f"{members_url}?filter={member_filter}&limit=100&fields=id,email", headers=headers
            )
            if response.status_code >= 400:
                raise CmsApplyEntitlementError(
                    f"ghost member listing returned status {response.status_code}"
                )
            members = json.loads(response.text).get("members") or []
            if not members:
                break
            progressed = False
            for member in members:
                member_id = member.get("id")
                if not member_id:
                    continue
                result = self._http_client.delete(url=f"{members_url}{member_id}/", headers=headers)
                if result.status_code in (200, 204):
                    deleted += 1
                    progressed = True
                else:
                    failed += 1
            if not progressed:
                break
        return {"deleted": deleted, "failed": failed}

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
        url = f"{base_url.rstrip('/')}/ghost/api/admin/members/?filter=email:'{_filter_value(email)}'&include=labels"

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

        # PG-229: Ghost has three member states and the gate has to cover all of
        # them. "paid" is a genuine Stripe subscriber: not comped, and carrying
        # no PayGlue label because PayGlue never touched them. Leaving it out
        # locked a publication's longest-paying readers out of its own paywall,
        # while yesterday's PayGlue buyer walked straight in.
        if member.get("comped") or member.get("status") in ("paid", "comped"):
            return {"active": True, "type": "subscription"}

        for label in member.get("labels", []):
            name = str(label.get("name", ""))
            # Both shapes: the bare status label written from PG-229 on, and
            # payglue-active:<provider> from before it. There is deliberately no
            # backfill in customer publications, so the old one has to keep
            # working for as long as those members exist.
            if name == "payglue-active" or name.startswith("payglue-active:"):
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

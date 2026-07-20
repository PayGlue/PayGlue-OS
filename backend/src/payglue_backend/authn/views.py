# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import logging
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import CharField, EmailField, Serializer
from rest_framework.views import APIView

from payglue_backend.authn.authentication import FirebaseBearerAuthentication
from payglue_backend.authn.invitations import normalize_email
from payglue_backend.authn.creem_access import (
    AccessValidationResult as CreemAccessValidationResult,
    CreemAccessError,
    CreemLicenseAlreadyUsedError,
    activate_license as activate_creem_license,
    cancel_subscription as cancel_creem_subscription,
    resolve_customer_email,
    validate_checkout_any_mode as validate_creem_checkout_any_mode,
)
from payglue_backend.authn.creem_webhook import (
    CreemWebhookError,
    extract_license_key,
    parse_checkout_completed,
    verify_signature as verify_creem_signature,
)
from payglue_backend.authn.polar_access import (
    PolarAccessError,
    validate_license_key,
)
from payglue_backend.authn.profile_gate import (
    InviteGateError,
    resolve_profile_with_invite_gate,
)
from payglue_backend.authn.verifier import (
    AuthVerificationUnavailableError,
    ExpiredAuthTokenError,
    InvalidAuthTokenError,
    get_auth_token_verifier,
)
from payglue_backend.authn.lifecycle_emails import send_lifecycle_email
from payglue_backend.http.throttling import DynamicScopedRateThrottle
from payglue_backend.authn.newsletter import route_checkout as route_newsletter_checkout
from payglue_backend.tenants.founding import record_sale_safely as record_founding_sale_safely
from payglue_backend.authn.step_up import (
    StepUpError,
    StepUpUnavailable,
    issue_challenge,
    require_step_up,
    verify_challenge,
)
from payglue_backend.tenants.cascade_delete import (
    clear_shared_tenant_billing_links,
    delete_tenant_cascade,
    sole_and_shared_tenants,
)
from payglue_backend.authn.lifecycle_emails import send_account_deleted_email
from payglue_backend.tenants.supabase_admin import SupabaseAdminError, delete_supabase_user
from payglue_backend.tenants.models import (
    AccessRedemption,
    BillingAccount,
    InvitationGrant,
    LicenseCode,
    LifecycleEmailTemplate,
    Plan,
    Tenant,
    TenantMembership,
    UserBackupCode,
    UserProfile,
    StepUpChallenge,
)

logger = logging.getLogger(__name__)


class HasUserProfile(BasePermission):
    def has_permission(self, request: Request, view: object) -> bool:
        del view
        return getattr(request, "user_profile", None) is not None


_BEARER_PATTERN = re.compile(
    r"^Bearer\s+(?P<token>[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)$",
    flags=re.IGNORECASE,
)


class AuthSessionView(APIView):
    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_session"

    def post(self, request: Request) -> Response:
        auth_header = request.headers.get("Authorization")
        if auth_header is None:
            return Response(
                {"detail": "Authorization header is required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        match = _BEARER_PATTERN.match(auth_header)
        if match is None:
            return Response(
                {"detail": "Authorization header must be Bearer <jwt>."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token = match.group("token")
        token_verifier = get_auth_token_verifier()
        try:
            claims = token_verifier.verify(token)
        except ExpiredAuthTokenError:
            return Response(
                {"detail": "Authentication token is expired."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except InvalidAuthTokenError:
            return Response(
                {"detail": "Authentication token is invalid."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except AuthVerificationUnavailableError:
            return Response(
                {"detail": "Authentication service is unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            profile = resolve_profile_with_invite_gate(claims)
        except IntegrityError:
            return Response(
                {"detail": "Authentication profile conflict."},
                status=status.HTTP_409_CONFLICT,
            )
        except InviteGateError as error:
            return Response(
                {"detail": str(error)},
                status=error.status_code,
            )
        request.user_profile = profile
        # PG-141: paused tenants must still show up (so the dashboard can
        # badge them and offer an upgrade path) -- only DISABLED/SUSPENDED
        # stay excluded here, matching every other ACTIVE-only membership
        # check in the codebase, which this one deliberately no longer does.
        memberships = list(
            TenantMembership.objects.filter(
                user_profile=profile,
                tenant__status__in=[Tenant.Status.ACTIVE, Tenant.Status.PAUSED],
            )
            .select_related("tenant")
            .order_by("tenant__slug")
        )

        billing_account = getattr(profile, "billing_account", None)
        billing_payload = None
        if billing_account is not None:
            grace_period_ends_at = None
            if billing_account.downgrade_detected_at is not None:
                grace_period_ends_at = billing_account.downgrade_detected_at + timedelta(
                    days=BillingAccount.GRACE_PERIOD_DAYS
                )
            billing_payload = {
                "plan": billing_account.plan.key,
                "downgrade_detected_at": billing_account.downgrade_detected_at,
                "grace_period_ends_at": grace_period_ends_at,
            }

        return Response(
            {
                "user": {
                    "id": profile.id,
                    "firebase_uid": profile.firebase_uid,
                    "email": profile.email,
                },
                "memberships": [
                    {
                        "tenant_slug": membership.tenant.slug,
                        "role": membership.role,
                        "status": membership.tenant.status,
                    }
                    for membership in memberships
                ],
                "billing": billing_payload,
            },
            status=status.HTTP_200_OK,
        )

class CheckoutInfoView(APIView):
    """Return the customer email for a completed Creem checkout.

    Used by the signup form to pre-fill the email field without creating
    an InvitationGrant — that only happens when the user submits.
    """

    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_invitation_validate"

    def get(self, request: Request) -> Response:
        checkout_id = request.query_params.get("checkout_id", "").strip()

        if not checkout_id:
            return Response(
                {"detail": "checkout_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Creem's return-URL redirect gives no mode indicator, so we can't
        # know upfront whether this checkout was sandbox or live — try both.
        sandbox_api_key = getattr(settings, "CREEM_SANDBOX_API_KEY", "")
        live_api_key = getattr(settings, "CREEM_API_KEY", "")

        if not sandbox_api_key and not live_api_key:
            return Response(
                {"detail": "Access validation is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            result = validate_creem_checkout_any_mode(checkout_id, sandbox_api_key, live_api_key)
        except CreemAccessError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"email": result.email}, status=status.HTTP_200_OK)


class CreemCheckoutWebhookView(APIView):
    """Receive Creem's checkout.completed webhook for PayGlue's own billing.

    Pre-authorizes the buyer's email (InvitationGrant) as soon as the purchase
    completes, and stores their Creem license key locally so the signup form
    can redeem it without calling Creem's license API (which doesn't return
    an email — see creem_access.py). Register this URL under Creem's
    dashboard > Developers > Webhooks. Not to be confused with the generic
    multi-tenant provider webhook ingest in webhooks/views.py (GOGU-135,
    customer-facing) — this is PayGlue's own checkout only.
    """

    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "webhook_ingest"

    def post(self, request: Request) -> Response:
        sandbox_secret = getattr(settings, "CREEM_SANDBOX_WEBHOOK_SECRET", "")
        live_secret = getattr(settings, "CREEM_WEBHOOK_SECRET", "")
        if not sandbox_secret and not live_secret:
            return Response(
                {"detail": "Webhook is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Same endpoint receives both sandbox and live deliveries (Creem's
        # dashboard registers webhooks per-mode but doesn't offer separate
        # URLs). Whichever secret verifies the signature tells us the mode —
        # more reliable than trusting an unverified `mode` field in the body.
        signature = request.headers.get("creem-signature", "")
        if sandbox_secret and verify_creem_signature(request.body, signature, sandbox_secret):
            use_sandbox = True
        elif live_secret and verify_creem_signature(request.body, signature, live_secret):
            use_sandbox = False
        else:
            return Response({"detail": "Invalid signature."}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            checkout = parse_checkout_completed(request.body)
        except CreemWebhookError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if checkout is None:
            # Any other event type — acknowledge and ignore.
            return Response(status=status.HTTP_200_OK)

        customer = checkout.get("customer")
        if not customer:
            return Response(
                {"detail": "checkout.completed payload has no customer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        creem_api_key = (
            getattr(settings, "CREEM_SANDBOX_API_KEY", "")
            if use_sandbox
            else getattr(settings, "CREEM_API_KEY", "")
        )

        try:
            email = resolve_customer_email(customer, creem_api_key, sandbox=use_sandbox)
        except CreemAccessError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not email:
            return Response(
                {"detail": "Could not resolve customer email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # PG-142: a checkout started from the in-dashboard Plans page (PG-150)
        # tags itself via metadata so we can update that exact existing
        # BillingAccount's plan directly, instead of running the InvitationGrant
        # flow below (which is for brand-new signups, not upgrades/downgrades
        # by someone who already has an account).
        metadata = checkout.get("metadata") or {}
        billing_account = None
        if metadata.get("source") == "dashboard_upgrade" and metadata.get("billing_account_id"):
            billing_account = BillingAccount.objects.filter(
                id=metadata["billing_account_id"]
            ).first()

        # PG-184: found live -- a checkout NOT started from our own Plans
        # page (a direct/external Creem checkout link, e.g. a marketing
        # email or a sandbox test link) skipped this branch entirely even
        # for an email that already has an account, since only the
        # dashboard flow tags itself. That created a second, parallel
        # subscription nothing ever linked to the existing BillingAccount
        # or cancelled. Treat any checkout for an already-known email the
        # same way as a dashboard-initiated upgrade/downgrade.
        if billing_account is None:
            existing_profile = UserProfile.objects.filter(email=email).first()
            if existing_profile is not None:
                billing_account = getattr(existing_profile, "billing_account", None)

        if billing_account is not None:
            product = checkout.get("product")
            product_id = product.get("id") if isinstance(product, dict) else product
            subscription = checkout.get("subscription")
            subscription_id = (
                subscription.get("id") if isinstance(subscription, dict) else subscription
            )
            customer_id = customer.get("id") if isinstance(customer, dict) else customer

            # Capture the previously-stored subscription before overwriting
            # it below -- for the untagged (PG-184) path this is the only
            # signal of "what to cancel", since there's no explicit
            # previous_subscription_id metadata to fall back on.
            previous_subscription_id = (
                metadata.get("previous_subscription_id") or billing_account.creem_subscription_id or None
            )
            just_downgraded = False

            if product_id:
                plan = Plan.objects.filter(creem_product_id=product_id).first() or Plan.objects.filter(
                    creem_product_id_annual=product_id
                ).first()
                if plan is not None:
                    # PG-141: this dashboard-switch branch is the only
                    # reliable, already-tested signal we have for a plan
                    # change -- Creem's own subscription.updated webhook
                    # isn't wired up (no verified payload to parse). A move
                    # to a lower-ranked plan starts the grace period; an
                    # upgrade back before enforcement runs clears it.
                    old_plan = billing_account.plan
                    billing_account.plan = plan
                    just_downgraded = plan.rank < old_plan.rank
                    if just_downgraded:
                        billing_account.downgrade_detected_at = timezone.now()
                    elif plan.rank >= old_plan.rank:
                        billing_account.downgrade_detected_at = None
            if customer_id:
                billing_account.creem_customer_id = str(customer_id)
            if subscription_id:
                billing_account.creem_subscription_id = str(subscription_id)
            billing_account.save()

            # PG-148: fires right where the signal already exists -- no new
            # webhook needed. Only after save() succeeds, so a DB failure
            # can't send an email describing a downgrade that didn't stick.
            if just_downgraded:
                send_lifecycle_email(billing_account, LifecycleEmailTemplate.Trigger.DOWNGRADE)

            # PG-150 follow-up: Creem's checkout API always creates a
            # brand new subscription -- it never replaces an existing
            # one, even for a same-plan monthly<->annual switch. Without
            # this, the customer keeps paying for the old plan in
            # parallel with the new one (found live: switching Solo ->
            # Studio left the Solo subscription active and still
            # billing). Cancel it immediately, not scheduled -- they're
            # covered by the new subscription already, there's no
            # access to preserve by waiting out its period.
            if previous_subscription_id and str(previous_subscription_id) != str(subscription_id):
                try:
                    cancel_creem_subscription(
                        str(previous_subscription_id), creem_api_key, sandbox=use_sandbox, mode="immediate"
                    )
                except CreemAccessError as exc:
                    # Found live (PG-141 test): this failing silently left
                    # a parallel un-cancelled subscription with no trace
                    # anywhere -- log it so a failed auto-cancel is at
                    # least visible and can be cleaned up manually.
                    logger.warning(
                        "Could not auto-cancel previous subscription %s during plan switch: %s",
                        previous_subscription_id, exc,
                    )

            # Counted here too, because a founding buyer whose email already
            # has an account takes this branch and would otherwise never be
            # counted. Non-founding products match no tier and are ignored.
            # Last thing before the return: the billing work above is done, so
            # nothing it did can be affected by this.
            record_founding_sale_safely(checkout, email)
            return Response(status=status.HTTP_200_OK)

        license_key = extract_license_key(checkout)

        # PG-201 diagnostics: activation kept showing "Inactive" after an external
        # checkout. Log (no secret values) whether the webhook fired and whether a
        # license key was found where extract_license_key looks -- an external
        # checkout may carry it elsewhere in the payload, or in a separate event.
        logger.info(
            "checkout.completed webhook: email=%s object_keys=%s license_key_found=%s",
            email,
            sorted(checkout.keys()),
            bool(license_key),
        )

        InvitationGrant.objects.update_or_create(
            email=email,
            defaults={
                "source": InvitationGrant.Source.CREEM_CHECKOUT,
                "license_key": license_key,
                "consumed_at": None,
            },
        )

        # PG-201: activate the license at Creem so its dashboard reflects the
        # purchase (Inactive 0/1 -> Active 1/1). Done here (not only at signup
        # redemption) because most buyers return via the checkout redirect, which
        # never carries the license key to the signup form -- so redemption-time
        # activation alone left every key "Inactive". Best-effort: a Creem hiccup
        # must never fail the webhook (Creem would just retry it forever).
        if license_key:
            try:
                payload = activate_creem_license(
                    license_key, email, creem_api_key, sandbox=use_sandbox
                )
                instance = payload.get("instance") if isinstance(payload, dict) else None
                instance_id = instance.get("id", "") if isinstance(instance, dict) else ""
                if instance_id:
                    InvitationGrant.objects.filter(email=email).update(
                        creem_license_instance_id=instance_id
                    )
                logger.info(
                    "Creem license activated for %s (instance=%s)", email, instance_id or "-"
                )
            except CreemLicenseAlreadyUsedError:
                logger.info("Creem license already active for %s", email)
            except CreemAccessError as exc:
                logger.warning("Creem license activation failed for %s: %s", email, exc)

        # Newsletter opt-in, if they ticked the box. route_checkout swallows its
        # own failures: a blog subscription that did not happen must never make
        # Creem retry a checkout whose billing side already succeeded.
        if route_newsletter_checkout(checkout):
            logger.info("Newsletter opt-in routed to the PayGlue blog for %s", email)

        # PG-210: count the sale against the founding ladder in pricing_tiers.
        # Deliberately last, and deliberately unable to raise -- the buyer's
        # grant and license are already in place by now, and a counter must
        # never be the reason a paid checkout's webhook fails.
        record_founding_sale_safely(checkout, email)

        return Response(status=status.HTTP_200_OK)


class AccessValidateSerializer(Serializer):
    email = EmailField()
    checkout_id = CharField(required=False, allow_blank=True, max_length=256)
    license_key = CharField(required=False, allow_blank=True, max_length=256)
    sandbox = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("checkout_id") and not attrs.get("license_key"):
            raise serializers.ValidationError(
                "Either checkout_id or license_key is required."
            )
        return attrs


def _activate_creem_license(license_key: str, instance_name: str, use_sandbox: bool) -> str:
    """Best-effort: tell Creem the license key was redeemed so it shows as
    'active' in Creem's dashboard. Returns the created instance id, or "" if no
    Creem API key is configured for this mode. Re-raises
    CreemLicenseAlreadyUsedError (so the caller can block a re-redemption) and
    CreemAccessError (so the caller can log-and-continue)."""
    api_key = (
        getattr(settings, "CREEM_SANDBOX_API_KEY", "")
        if use_sandbox
        else getattr(settings, "CREEM_API_KEY", "")
    )
    if not api_key:
        return ""
    payload = activate_creem_license(license_key, instance_name, api_key, sandbox=use_sandbox)
    instance = payload.get("instance")
    return instance.get("id", "") if isinstance(instance, dict) else ""


class AccessValidateView(APIView):
    """Validate a Creem checkout/license or legacy Polar license key, create an InvitationGrant.

    Called from the signup form before the user creates their Supabase account.
    On success, the email is allowed through the invite gate on first login.

    License-key redemption checks our own DB first (InvitationGrant.license_key,
    populated by the checkout.completed webhook — see CreemCheckoutWebhookView)
    before falling back to Polar's API. Creem's license endpoints don't return
    a customer email (see creem_access.py), so a key that isn't in our DB can
    only be a legacy Polar purchase from before the cutover.
    """

    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_invitation_validate"

    def post(self, request: Request) -> Response:
        serializer = AccessValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        checkout_id: str = serializer.validated_data.get("checkout_id", "").strip()
        license_key: str = serializer.validated_data.get("license_key", "").strip()
        provided_email = normalize_email(serializer.validated_data["email"])
        use_sandbox: bool = serializer.validated_data.get("sandbox", False)

        # Dev bypass for signup testing without a real Creem/Polar purchase
        # (PG-142). Deliberately NOT the frontend's "dev" convenience string
        # -- that's only ever compared against a real secret configured in
        # Railway, so this only works for someone who actually knows the
        # value, never someone reading the public JS bundle. Empty setting
        # (the default) disables this branch entirely.
        is_dev_bypass = bool(settings.DEV_BYPASS_LICENSE_KEY) and secrets.compare_digest(
            license_key, settings.DEV_BYPASS_LICENSE_KEY
        )

        # PG-183: set when the entered key is a redeemable PayGlue license code.
        # Carries the tester plan + access window through to BillingAccount creation.
        payglue_code: LicenseCode | None = None
        # Set when the entered key is a Creem license key -- activated at Creem on
        # first redemption so its dashboard reflects the redemption.
        creem_license_key = ""
        creem_instance_id = ""

        try:
            if is_dev_bypass:
                result = CreemAccessValidationResult(email=provided_email)
                kind = AccessRedemption.Kind.LICENSE_KEY
                # Keyed per-email, not by the shared secret itself, so the
                # same dev key can be reused for any number of distinct test
                # emails instead of only ever redeeming once.
                redemption_id = f"dev-bypass:{provided_email}"
                source_is_creem = None  # signals the dev-bypass source below
            elif checkout_id:
                # Creem's return-URL redirect gives no mode indicator — try
                # both sandbox and live rather than trusting a client-supplied
                # sandbox flag for a purchase we didn't originate the URL for.
                sandbox_api_key = getattr(settings, "CREEM_SANDBOX_API_KEY", "")
                live_api_key = getattr(settings, "CREEM_API_KEY", "")
                if not sandbox_api_key and not live_api_key:
                    return Response(
                        {"detail": "Access validation is not configured."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
                result = validate_creem_checkout_any_mode(checkout_id, sandbox_api_key, live_api_key)
                kind = AccessRedemption.Kind.CHECKOUT
                redemption_id = checkout_id
                source_is_creem = True
            elif license_key.strip().upper().startswith("PAYGLUE-"):
                # PG-183: a PayGlue-issued tester code. Email-agnostic -- whoever
                # holds the code signs up with their own address, up to the code's
                # max_activations (enforced under a row lock in the txn below).
                code_value = license_key.strip().upper()
                payglue_code = LicenseCode.objects.filter(code=code_value).first()
                if payglue_code is None or not payglue_code.is_redeemable:
                    return Response(
                        {"detail": "This invite code is invalid or has already been fully used."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                result = CreemAccessValidationResult(email=provided_email)
                kind = AccessRedemption.Kind.LICENSE_KEY
                # Per-email so several testers can each redeem the same shared code.
                redemption_id = f"payglue-code:{code_value}:{provided_email}"
                source_is_creem = None
            else:
                creem_grant = InvitationGrant.objects.filter(license_key=license_key).first()
                source_is_creem = creem_grant is not None
                if creem_grant:
                    result = CreemAccessValidationResult(email=creem_grant.email)
                    creem_license_key = license_key
                else:
                    polar_api_key = (
                        getattr(settings, "POLAR_SANDBOX_API_KEY", "")
                        if use_sandbox
                        else getattr(settings, "POLAR_API_KEY", "")
                    )
                    polar_org_id = (
                        getattr(settings, "POLAR_SANDBOX_ORGANIZATION_ID", "")
                        if use_sandbox
                        else getattr(settings, "POLAR_ORGANIZATION_ID", "")
                    )
                    if not polar_api_key:
                        return Response(
                            {"detail": "Access validation is not configured."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE,
                        )
                    result = validate_license_key(license_key, polar_api_key, polar_org_id, sandbox=use_sandbox)
                kind = AccessRedemption.Kind.LICENSE_KEY
                redemption_id = license_key.strip().upper()
        except (CreemAccessError, PolarAccessError) as exc:
            # Never surface the raw provider error text to the client -- it
            # can include internal detail (e.g. "Polar API 401: {...}" when
            # POLAR_API_KEY itself has expired) that's meaningless to a
            # customer and looks like a leak. Log it for us, show them a
            # generic, actionable message instead.
            logger.warning(
                "Access validation rejected checkout_id=%r license_key=%r: %s",
                checkout_id, license_key, exc,
            )
            return Response(
                {"detail": "This invite code is invalid or has expired. Please check it and try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Email on the Polar order must match what the user typed
        if result.email != provided_email:
            return Response(
                {"detail": "Email does not match the purchase record. "
                           "Please use the email address you used to buy PayGlue."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            # Prevent the same checkout/key from creating two accounts
            if AccessRedemption.objects.filter(redemption_id=redemption_id).exists():
                existing = AccessRedemption.objects.get(redemption_id=redemption_id)
                if existing.email != provided_email:
                    return Response(
                        {"detail": "This access key has already been redeemed."},
                        status=status.HTTP_409_CONFLICT,
                    )
                # Same email retrying — idempotent, just refresh the grant
            else:
                # PG-183: count one activation against the shared code, re-checking
                # the limit under a row lock so a burst of "first come first served"
                # redemptions can never exceed max_activations.
                if payglue_code is not None:
                    payglue_code = LicenseCode.objects.select_for_update().get(
                        pk=payglue_code.pk
                    )
                    if not payglue_code.is_redeemable:
                        return Response(
                            {"detail": "This invite code has already been fully used."},
                            status=status.HTTP_409_CONFLICT,
                        )
                    payglue_code.activation_count += 1
                    payglue_code.save(update_fields=["activation_count"])
                elif creem_license_key:
                    # Mark the key redeemed at Creem (dashboard accuracy). Our
                    # AccessRedemption above is the real reuse guard, so a Creem
                    # API hiccup must not block a paying customer -- log and go on.
                    # Only Creem's own "already activated / limit reached" blocks.
                    try:
                        creem_instance_id = _activate_creem_license(
                            creem_license_key, provided_email, use_sandbox
                        )
                    except CreemLicenseAlreadyUsedError:
                        # Normal now: the checkout.completed webhook already
                        # activated the key at purchase time. Reuse is guarded
                        # locally by AccessRedemption, so this is not a block.
                        pass
                    except CreemAccessError as exc:
                        logger.warning(
                            "Creem license activation failed for %s: %s", provided_email, exc
                        )
                AccessRedemption.objects.create(
                    kind=kind,
                    redemption_id=redemption_id,
                    email=provided_email,
                )

            if payglue_code is not None:
                source = InvitationGrant.Source.PAYGLUE_LICENSE
            elif source_is_creem is None:
                source = InvitationGrant.Source.MANUAL
            elif source_is_creem:
                source = InvitationGrant.Source.CREEM_CHECKOUT
            else:
                source = InvitationGrant.Source.POLAR_LICENSE
            grant_defaults = {
                "source": source,
                "consumed_at": None,
                "license_code": payglue_code,
            }
            if creem_instance_id:
                grant_defaults["creem_license_instance_id"] = creem_instance_id
            InvitationGrant.objects.update_or_create(
                email=provided_email,
                defaults=grant_defaults,
            )

        return Response({"valid": True}, status=status.HTTP_200_OK)


BACKUP_CODE_COUNT = 10
_BACKUP_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I/l


def _generate_backup_code() -> str:
    chars = [secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(8)]
    return f"{''.join(chars[:4])}-{''.join(chars[4:])}"


class MfaBackupCodesView(APIView):
    """Generate or check status of 2FA recovery codes for the current user.

    Codes are shown to the user exactly once, at generation time -- we only
    ever store their hash. Generating a new batch invalidates any unconsumed
    codes from a previous batch.
    """

    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [HasUserProfile]

    def get(self, request: Request) -> Response:
        remaining = UserBackupCode.objects.filter(
            user_profile=request.user_profile, consumed_at__isnull=True
        ).count()
        return Response({"remaining": remaining})

    def post(self, request: Request) -> Response:
        codes = [_generate_backup_code() for _ in range(BACKUP_CODE_COUNT)]
        with transaction.atomic():
            UserBackupCode.objects.filter(
                user_profile=request.user_profile, consumed_at__isnull=True
            ).delete()
            UserBackupCode.objects.bulk_create(
                UserBackupCode(
                    user_profile=request.user_profile, code_hash=make_password(code)
                )
                for code in codes
            )
        return Response({"codes": codes}, status=status.HTTP_201_CREATED)


class MfaBackupCodeVerifySerializer(Serializer):
    code = CharField(min_length=4, max_length=32)


class MfaBackupCodeVerifyView(APIView):
    """Consume one backup code as an alternative to a TOTP code at login.

    Requires the same Bearer token an AAL1 (magic-link-only) Supabase
    session already carries -- our backend doesn't distinguish AAL levels,
    that gate lives in the frontend router. This endpoint just proves
    possession of a valid recovery code for this account.
    """

    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [HasUserProfile]
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_mfa_backup_code_verify"

    def post(self, request: Request) -> Response:
        serializer = MfaBackupCodeVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submitted = serializer.validated_data["code"].strip().upper()

        candidates = UserBackupCode.objects.filter(
            user_profile=request.user_profile, consumed_at__isnull=True
        )
        for candidate in candidates:
            if check_password(submitted, candidate.code_hash):
                candidate.consumed_at = timezone.now()
                candidate.save(update_fields=["consumed_at"])
                return Response({"valid": True}, status=status.HTTP_200_OK)

        return Response(
            {"valid": False, "detail": "Invalid or already-used backup code."},
            status=status.HTTP_400_BAD_REQUEST,
        )


class _StepUpRequestSerializer(Serializer):
    purpose = CharField(max_length=32)


class _StepUpVerifySerializer(Serializer):
    purpose = CharField(max_length=32)
    code = CharField(max_length=16)


def _bearer_token(request: Request) -> str:
    """The caller's raw JWT, which the TOTP path forwards to Supabase.

    Authentication already verified it; we only need the string back, because
    Supabase must see the user's own token to check their own factor.
    """
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


class StepUpRequestView(APIView):
    """Start a step-up confirmation (PG-203).

    Answers which proof the account will be asked for, so the overlay knows
    whether to show "open your authenticator" or "check your email".
    """

    authentication_classes = [FirebaseBearerAuthentication]
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_step_up_request"

    def post(self, request: Request) -> Response:
        serializer = _StepUpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            issued = issue_challenge(
                request.user, serializer.validated_data["purpose"], _bearer_token(request)
            )
        except StepUpError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except StepUpUnavailable as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"method": issued.method, "challenge_id": issued.challenge_id})


class StepUpVerifyView(APIView):
    """Check the code and hand back a single-use grant token (PG-203)."""

    authentication_classes = [FirebaseBearerAuthentication]
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_step_up_verify"

    def post(self, request: Request) -> Response:
        serializer = _StepUpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = verify_challenge(
                request.user,
                serializer.validated_data["purpose"],
                serializer.validated_data["code"],
                _bearer_token(request),
            )
        except StepUpError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except StepUpUnavailable as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"token": token})


class DeleteAccountView(APIView):
    """Self-service account deletion, for real this time.

    Until now the dashboard's "Delete account" button called `supabase.auth
    .signOut()` and redirected to `/?deleted=1`. Nothing was deleted. The user
    was shown a confirmation for something that had not happened, which is a
    problem well beyond UX polish: it is the exact request the GDPR gives
    people a right to, answered with a lie.

    The deletion logic itself already existed for the admin and the lapsed-
    account cron (PG-187, PG-190). This exposes the same path to the account
    owner, in the same order, so all three routes stay identical:

      shared-tenant billing links cleared -> solely-owned tenants cascaded ->
      profile deleted -> Supabase auth user deleted

    Supabase comes last and outside the transaction on purpose. If it fails,
    the local data is already gone (the part we are legally obliged to remove)
    and the orphaned auth user is a loose end an admin can sweep, rather than a
    rollback that resurrects deleted tenants.
    """

    authentication_classes = [FirebaseBearerAuthentication]
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_step_up_verify"

    def delete(self, request: Request) -> Response:
        profile = request.user_profile
        try:
            require_step_up(request, profile, StepUpChallenge.Purpose.DELETE_ACCOUNT)
        except StepUpError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        supabase_uid = profile.firebase_uid
        deleted_email = profile.email
        sole_owner_tenants, shared_tenants = sole_and_shared_tenants(profile)
        with transaction.atomic():
            clear_shared_tenant_billing_links(profile, shared_tenants)
            for tenant in sole_owner_tenants:
                delete_tenant_cascade(tenant)
            profile.delete()

        try:
            delete_supabase_user(supabase_uid)
        except SupabaseAdminError:
            # Local data is gone either way; log loudly so the leftover auth
            # user gets cleaned up rather than silently lingering.
            logger.exception("Deleted profile %s but could not delete Supabase user", supabase_uid)

        # Last, and only once everything above succeeded: a receipt for an
        # account that is already gone. Address captured before the delete,
        # since the row it lived on no longer exists.
        send_account_deleted_email(deleted_email)

        return Response(status=status.HTTP_204_NO_CONTENT)

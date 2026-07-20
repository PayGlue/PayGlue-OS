# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import hashlib
import secrets

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


def _generate_webhook_secret() -> str:
    return secrets.token_urlsafe(24)


def _generate_license_code() -> str:
    # PG-183: PayGlue-issued invite code, human-shareable (Reddit, DMs, etc.).
    # token_hex(5) -> 10 uppercase hex chars, e.g. PAYGLUE-A1B2C3D4E5.
    return f"PAYGLUE-{secrets.token_hex(5).upper()}"


class Tenant(TenantMixin):
    # PayGlue does NOT use per-tenant Postgres schemas -- all tenant content is
    # keyed by the tenant_slug string column, never a schema. django_tenants'
    # default save()/delete() would otherwise call migrate_schemas / drop schema
    # (neither is wired up here), which 500s the moment a tenant without a schema
    # is saved -- e.g. editing an old tenant in the admin threw
    # "CommandError: Unknown command: 'migrate_schemas'". Turning schema
    # management off makes save()/delete() never touch schemas.
    auto_create_schema = False
    auto_drop_schema = False

    class Status(models.TextChoices):
        ACTIVE = "active", "active"
        SUSPENDED = "suspended", "suspended"
        DISABLED = "disabled", "disabled"
        # PG-141: set by enforce_downgrade_grace_periods once a plan
        # downgrade's 1-month grace period expires without the owner
        # upgrading back. Distinct from SUSPENDED (provider/abuse-initiated)
        # and DISABLED (permanent) -- reactivates automatically once the
        # owner upgrades again, no admin action needed.
        PAUSED = "paused", "paused"

    slug = models.SlugField(
        max_length=64,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
                message="Slug must use lowercase letters, numbers, and hyphens.",
            )
        ],
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    webhook_secret = models.CharField(
        max_length=64,
        unique=True,
        default=_generate_webhook_secret,
        help_text="Per-tenant secret embedded in this tenant's webhook URLs, replacing the old shared global endpoint token.",
    )
    # Nullable: a handful of pre-billing tenants may not resolve to an owner
    # with a clean membership row. check_plan_limit() treats null as
    # unlimited/legacy-exempt rather than forcing every row to backfill
    # cleanly under a NOT NULL constraint.
    billing_account = models.ForeignKey(
        "BillingAccount",
        on_delete=models.PROTECT,
        related_name="tenants",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self) -> None:
        super().clean()
        if self.pk is not None:
            original_slug = (
                Tenant.objects.filter(pk=self.pk).values_list("slug", flat=True).first()
            )
            if original_slug is not None and original_slug != self.slug:
                raise ValidationError(
                    {"slug": "Slug is immutable and cannot be changed after creation."}
                )

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.slug


class UserProfile(models.Model):
    firebase_uid = models.CharField(max_length=255, unique=True)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    @property
    def has_live_billing(self) -> bool:
        """PG-187: True if this user is a live paying customer -- an owner with a
        BillingAccount that has not yet entered the post-cancellation deletion
        grace period. Only owners ever have a BillingAccount, so members, invites
        and test users are always False. Used to red-flag them in the admin so a
        real payer is never deleted by accident. (The reverse OneToOne descriptor
        raises an AttributeError subclass when absent, so getattr's default fires.)
        """
        billing_account = getattr(self, "billing_account", None)
        return billing_account is not None and billing_account.cancellation_detected_at is None

    def __str__(self) -> str:
        return self.email


class Plan(models.Model):
    class Key(models.TextChoices):
        SOLO = "solo", "Solo"
        STUDIO = "studio", "Studio"
        AGENCY = "agency", "Agency"
        FOUNDING = "founding", "Founding Member"

    key = models.CharField(max_length=32, choices=Key.choices, unique=True)
    name = models.CharField(max_length=64)
    # null = unlimited (Agency, Founding Member)
    max_tenants = models.PositiveIntegerField(null=True, blank=True)
    max_buy_buttons_per_tenant = models.PositiveIntegerField(null=True, blank=True)
    max_paywalls_per_tenant = models.PositiveIntegerField(null=True, blank=True)
    max_pricing_tables_per_tenant = models.PositiveIntegerField(null=True, blank=True)
    max_providers_per_tenant = models.PositiveIntegerField(null=True, blank=True)
    max_team_members_per_tenant = models.PositiveIntegerField(null=True, blank=True)
    creem_product_id = models.CharField(max_length=64, blank=True, default="")
    creem_product_id_annual = models.CharField(max_length=64, blank=True, default="")

    # PG-141: not a DB column -- only 4 fixed keys, so a plain mapping is
    # simpler than a migration. Agency and Founding Member are both
    # "unlimited" (see max_tenants comment above), so they share a rank;
    # a downgrade is any move to a strictly lower rank.
    RANK = {
        Key.SOLO: 1,
        Key.STUDIO: 2,
        Key.AGENCY: 3,
        Key.FOUNDING: 3,
    }

    @property
    def rank(self) -> int:
        return self.RANK.get(self.key, 0)

    def __str__(self) -> str:
        return self.name


class BillingAccount(models.Model):
    # PG-141: shared by enforce_downgrade_grace_periods (enforcement) and
    # AuthSessionView (frontend grace-period banner) so both agree on the
    # same window without duplicating the number.
    GRACE_PERIOD_DAYS = 30

    owner = models.OneToOneField(
        UserProfile, on_delete=models.CASCADE, related_name="billing_account"
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, related_name="billing_accounts"
    )
    creem_customer_id = models.CharField(max_length=64, blank=True, default="")
    creem_subscription_id = models.CharField(max_length=64, blank=True, default="")
    # PG-141: set when a checkout webhook detects a move to a lower-ranked
    # plan; cleared if the owner upgrades back before the grace period
    # expires. enforce_downgrade_grace_periods reads this to decide which
    # accounts are due for tenant pausing.
    downgrade_detected_at = models.DateTimeField(null=True, blank=True)
    # PG-148: bookkeeping only, never displayed -- the last subscription
    # state send_lifecycle_emails observed via _creem_subscription_for_switch,
    # so the next run can detect a *transition* (e.g. active -> gone) instead
    # of re-sending on every poll. "ended" is our own value, not a literal
    # Creem status string -- Creem's lookup helper stops returning a
    # subscription at all once it's no longer active/trialing, so there's
    # nothing to read a real terminal status off of.
    last_known_subscription_status = models.CharField(max_length=32, blank=True, default="")
    last_known_cancel_at_period_end = models.BooleanField(default=False)
    # PG-190: set once send_lifecycle_emails confirms Creem's subscription
    # status is the literal terminal value "canceled" (fetched fresh by id,
    # not inferred from an absence) -- starts the 30-day deletion grace
    # period. There is deliberately no "no active plan" state for an owner:
    # team members never have their own BillingAccount, so a lapsed owner's
    # account is either paying or on its way to full deletion.
    cancellation_detected_at = models.DateTimeField(null=True, blank=True)
    # PG-190: set when the poll sees a Creem status that isn't clearly
    # active/trialing/scheduled_cancel NOR a confirmed "canceled" -- e.g.
    # past_due/unpaid/paused, or the raw status fetch itself failed. These
    # can be a transient payment retry, not a real cancellation, and only
    # André (checking Creem directly) can tell the difference -- so nothing
    # here starts the deletion clock automatically.
    needs_admin_review = models.BooleanField(default=False)
    admin_review_reason = models.CharField(max_length=64, blank=True, default="")
    # PG-183: this account was provisioned by redeeming a PayGlue license code,
    # not a Creem purchase. It shows as "Tester" in billing. tester_access_expires_at
    # is null for a "never expires" code; otherwise expire_tester_access starts the
    # normal 30-day cancellation grace once it passes.
    is_tester = models.BooleanField(default=False)
    # PG-210: which founding batch this account joined in, and the rate it
    # locked. Stamped once at signup from the FoundingSale that matches the
    # purchase email; the rate is copied rather than derived so a later change
    # to the ladder cannot move it.
    founding_tier = models.PositiveSmallIntegerField(null=True, blank=True)
    founding_price_cents = models.PositiveIntegerField(null=True, blank=True)
    tester_access_expires_at = models.DateTimeField(null=True, blank=True)
    license_code = models.ForeignKey(
        "LicenseCode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="billing_accounts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.owner.email} ({self.plan.key})"


class LifecycleEmailTemplate(models.Model):
    """PG-148: admin-editable retention/lifecycle emails for PayGlue's own
    paying customers (tenant owners), triggered by their own subscription's
    lifecycle -- not a tenant's own end-customers (that's a separate,
    unrelated concern in webhooks/adapters/*)."""

    class Trigger(models.TextChoices):
        DOWNGRADE = "downgrade", "downgrade"
        SCHEDULED_CANCELLATION = "scheduled_cancellation", "scheduled_cancellation"
        SUBSCRIPTION_ENDED = "subscription_ended", "subscription_ended"
        CANCELLATION_REMINDER_15D = "cancellation_reminder_15d", "cancellation_reminder_15d"
        CANCELLATION_FINAL_WARNING = "cancellation_final_warning", "cancellation_final_warning"
        # PG-192: operational alert (not a subscription-lifecycle mail) -- warns
        # the creator when their Ghost delivery is repeatedly failing.
        GHOST_DELIVERY_FAILING = "ghost_delivery_failing", "ghost_delivery_failing"
        # PG-182: emailed to the current owner when an ownership transfer is
        # requested, asking them to confirm/reject it in the dashboard.
        OWNER_TRANSFER_REQUESTED = "owner_transfer_requested", "owner_transfer_requested"
        # PG-182 follow-up: the other three sides of that same flow. Without
        # these only the deciding owner ever hears about a transfer -- the
        # proposed owner and the requester were left guessing.
        OWNER_TRANSFER_PROPOSED = "owner_transfer_proposed", "owner_transfer_proposed"
        OWNER_TRANSFER_CONFIRMED = "owner_transfer_confirmed", "owner_transfer_confirmed"
        OWNER_TRANSFER_REJECTED = "owner_transfer_rejected", "owner_transfer_rejected"
        # Two templates, not one: the person who lost access and the people who
        # need a record of it are reading about different events. "You have
        # been removed" is wrong copy for an owner, and "X was removed" is a
        # strange way to tell somebody it was them.
        TEAM_MEMBER_REMOVED = "team_member_removed", "team_member_removed"
        TEAM_MEMBER_REMOVED_NOTICE = "team_member_removed_notice", "team_member_removed_notice"
        ACCOUNT_DELETED = "account_deleted", "account_deleted"
        # Onboarding sequence. Unlike the triggers above these fire once per
        # account and never again, which the partial constraint on
        # LifecycleEmailLog enforces rather than trusting every caller to
        # check first.
        ONBOARDING_WELCOME = "onboarding_welcome", "onboarding_welcome"
        ONBOARDING_DAY15 = "onboarding_day15", "onboarding_day15"

    trigger = models.CharField(max_length=32, choices=Trigger.choices, unique=True)
    subject = models.CharField(max_length=255)
    body = models.TextField(
        help_text=(
            "Plain text. Placeholders depend on the trigger: the subscription "
            "triggers expose $email and $plan; ghost_delivery_failing exposes "
            "$email, $tenant and $url; the owner_transfer_* triggers expose "
            "$tenant, $url, $new_owner and $previous_owner. Missing/unknown "
            "placeholders are left as-is, never crash the send."
        )
    )
    enabled = models.BooleanField(
        default=True,
        help_text="No template, or disabled, means this trigger simply doesn't send anything -- fails safe, not loud.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.trigger} ({'on' if self.enabled else 'off'})"


class LifecycleEmailLog(models.Model):
    """PG-148: audit trail of every lifecycle email actually sent. Not used
    for dedup logic itself -- that's handled by comparing against
    BillingAccount.last_known_* before ever calling send_lifecycle_email --
    this is purely for André to see what went out and when."""

    billing_account = models.ForeignKey(
        BillingAccount, on_delete=models.CASCADE, related_name="lifecycle_email_log"
    )
    trigger = models.CharField(max_length=32, choices=LifecycleEmailTemplate.Trigger.choices)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]
        constraints = [
            # Only the onboarding pair is once-per-account. A blanket unique
            # constraint would be wrong: ghost_delivery_failing fires per
            # incident and the transfer triggers fire per transfer, so those
            # legitimately repeat.
            models.UniqueConstraint(
                fields=["billing_account", "trigger"],
                condition=models.Q(trigger__in=["onboarding_welcome", "onboarding_day15"]),
                name="uniq_onboarding_email_per_account",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.trigger} -> {self.billing_account.owner.email} at {self.sent_at:%Y-%m-%d %H:%M}"


class LicenseCode(models.Model):
    """PG-183: a PayGlue-issued invite code, redeemable at signup WITHOUT a Creem
    purchase. Grants a chosen plan's limits as a "Tester" for a fixed window (or
    forever). When a limited window ends, the account enters the same 30-day
    deletion grace as a real cancelled subscription (PG-190), nudging the tester
    to pick a plan before deletion. André shares these on Reddit/socials/DMs with
    a max-activation count ("5x, first come first served")."""

    class AccessDuration(models.IntegerChoices):
        NEVER = 0, "Never expires"
        SEVEN_DAYS = 7, "7 days"
        FOURTEEN_DAYS = 14, "14 days"
        THIRTY_DAYS = 30, "30 days"

    code = models.CharField(
        max_length=40, unique=True, db_index=True, default=_generate_license_code
    )
    plan = models.ForeignKey(
        "Plan", on_delete=models.PROTECT, related_name="license_codes"
    )
    access_days = models.PositiveIntegerField(
        choices=AccessDuration.choices,
        default=AccessDuration.NEVER,
        help_text=(
            "How long the redeeming tester keeps full access before the 30-day "
            "deletion grace period starts. 0 = never expires (permanent free tester)."
        ),
    )
    max_activations = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="How many testers may redeem this code. Leave blank for unlimited.",
    )
    activation_count = models.PositiveIntegerField(default=0)
    label = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Optional note for yourself (campaign, source, etc.).",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.code

    @property
    def activations_remaining(self) -> int | None:
        """None = unlimited."""
        if self.max_activations is None:
            return None
        return max(0, self.max_activations - self.activation_count)

    @property
    def is_redeemable(self) -> bool:
        return self.is_active and (
            self.max_activations is None or self.activation_count < self.max_activations
        )


class InvitationGrant(models.Model):
    class Source(models.TextChoices):
        PREFINERY = "prefinery", "Prefinery"
        POLAR_CHECKOUT = "polar_checkout", "Polar Checkout"
        POLAR_LICENSE = "polar_license", "Polar License Key"
        CREEM_CHECKOUT = "creem_checkout", "Creem Checkout"
        # PG-183: redeemed a PayGlue-issued license code (tester, no Creem).
        PAYGLUE_LICENSE = "payglue_license", "PayGlue License Code"
        MANUAL = "manual", "Manual"

    email = models.EmailField(unique=True)
    invitation_code_prefix = models.CharField(max_length=16, blank=True, default="")
    # Prefinery isn't used any more (PG-142) -- PREFINERY stays in the choices
    # for any historical rows, but MANUAL is the sensible default now for
    # anything that doesn't explicitly set a source (e.g. the Django admin).
    source = models.CharField(
        max_length=32, choices=Source.choices, default=Source.MANUAL
    )
    # Set for CREEM_CHECKOUT grants created from the checkout.completed webhook.
    # Creem's license API doesn't return a customer email (see creem_access.py),
    # so we resolve email once via webhook and let the signup form redeem
    # against this local value instead of calling Creem's license endpoints.
    license_key = models.CharField(max_length=64, blank=True, default="", db_index=True)
    # PG-183: set for PAYGLUE_LICENSE grants -- carries the tester plan + access
    # window from signup validation through to BillingAccount creation (which
    # only happens later, when the tester makes their first publication).
    license_code = models.ForeignKey(
        "LicenseCode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invitation_grants",
    )
    # Set when a Creem license key is activated at Creem on redemption (the
    # instance id Creem returns), so the key shows as used in Creem's dashboard
    # and we could deactivate it later.
    creem_license_instance_id = models.CharField(max_length=64, blank=True, default="")
    verified_at = models.DateTimeField(auto_now=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.email


class AccessRedemption(models.Model):
    """Tracks Polar checkout IDs and license keys that have already been used to
    create an InvitationGrant, preventing double-redemption."""

    class Kind(models.TextChoices):
        CHECKOUT = "checkout", "Checkout"
        LICENSE_KEY = "license_key", "License Key"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    redemption_id = models.CharField(max_length=256, unique=True)
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["redemption_id"])]

    def __str__(self) -> str:
        return f"{self.email} ({self.kind})"


class TenantMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "owner"
        ADMIN = "admin", "admin"
        BILLING_ADMIN = "billing_admin", "billing_admin"
        SUPPORT_READONLY = "support_readonly", "support_readonly"

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="memberships"
    )
    user_profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="tenant_memberships",
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user_profile"],
                name="unique_tenant_user_membership",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_profile.email} @ {self.tenant.slug} ({self.role})"


class OwnershipTransferRequest(models.Model):
    """PG-182: an owner change is not applied immediately. An owner or admin
    requests transferring ownership to another member; the CURRENT owner is
    emailed and must confirm (or reject) it via a fresh dashboard login under
    Team -- protection against a hijacked session or accidental/malicious
    transfer of a billing-critical account. Exactly one owner per tenant is
    enforced: on confirm the new member becomes owner and the old owner is
    demoted to BILLING_ADMIN (billing / the Creem subscription stays on the
    original payer, so they keep the billing role). billing_admin is otherwise
    not an assignable role in the team UI -- it only appears as the result of a
    transfer."""

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        CONFIRMED = "confirmed", "confirmed"
        REJECTED = "rejected", "rejected"
        CANCELLED = "cancelled", "cancelled"

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="ownership_transfers"
    )
    current_owner = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="ownership_transfers_out"
    )
    new_owner = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="ownership_transfers_in"
    )
    requested_by = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="ownership_transfers_requested"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # At most one pending transfer per tenant at a time.
            models.UniqueConstraint(
                fields=["tenant"],
                condition=models.Q(status="pending"),
                name="unique_pending_ownership_transfer_per_tenant",
            )
        ]

    def __str__(self) -> str:
        return (
            f"{self.tenant.slug}: {self.current_owner.email} -> "
            f"{self.new_owner.email} ({self.status})"
        )


class BillingProfile(models.Model):
    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="billing_profile",
    )
    legal_name = models.CharField(max_length=255, blank=True, default="")
    billing_email = models.EmailField(blank=True, default="")
    country_code = models.CharField(max_length=2, blank=True, default="")
    tax_id = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Billing profile for {self.tenant.slug}"


class PublicAuditEvent(models.Model):
    class EventType(models.TextChoices):
        TEAM_MEMBER_CREATED = "team.member_created", "team.member_created"
        TEAM_MEMBER_ROLE_UPDATED = (
            "team.member_role_updated",
            "team.member_role_updated",
        )
        TEAM_MEMBER_REMOVED = "team.member_removed", "team.member_removed"
        BILLING_PROFILE_UPDATED = "billing.profile_updated", "billing.profile_updated"
        INTEGRATION_CREDENTIALS_WRITTEN = (
            "integration.credentials_written",
            "integration.credentials_written",
        )
        EVENT_REPLAY_REQUESTED = "event.replay_requested", "event.replay_requested"
        TEST_EVENT_SENT = "connection.test_event_sent", "connection.test_event_sent"
        SERVICE_PIN_GENERATED = "service_pin.generated", "service_pin.generated"
        SERVICE_PIN_REVOKED = "service_pin.revoked", "service_pin.revoked"
        OWNERSHIP_TRANSFER_REQUESTED = "team.ownership_transfer_requested", "team.ownership_transfer_requested"
        OWNERSHIP_TRANSFER_CONFIRMED = "team.ownership_transfer_confirmed", "team.ownership_transfer_confirmed"
        OWNERSHIP_TRANSFER_REJECTED = "team.ownership_transfer_rejected", "team.ownership_transfer_rejected"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="public_audit_events",
    )
    actor_membership = models.ForeignKey(
        TenantMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emitted_audit_events",
    )
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=128, blank=True, default="")
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "event_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} on {self.tenant.slug}"


def _generate_service_pin_code() -> str:
    return f"PGS-{secrets.randbelow(100_000):05d}"


class ServicePin(models.Model):
    """A customer-generated, time-limited consent code (e.g. "PGS-12345") the
    customer emails to PayGlue support to explicitly authorize support staff
    to make active changes to their tenant while investigating a ticket --
    not required for read-only debugging. See GOGU-129.
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="service_pins"
    )
    code = models.CharField(max_length=16, unique=True, default=_generate_service_pin_code)
    created_by = models.ForeignKey(
        TenantMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_service_pins",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} for {self.tenant.slug}"


class TenantDomain(DomainMixin):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class UserBackupCode(models.Model):
    """One-time recovery codes for account 2FA (TOTP via Supabase MFA).

    Supabase's native MFA has no backup-code concept, so this is our own
    recovery mechanism, checked by the frontend's login gate as an
    alternative to a TOTP code when a user has lost their authenticator.
    Codes are stored hashed (never recoverable), single-use.
    """

    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="backup_codes"
    )
    code_hash = models.CharField(max_length=128)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user_profile", "consumed_at"]),
        ]

    def __str__(self) -> str:
        status = "consumed" if self.consumed_at else "active"
        return f"Backup code for {self.user_profile.email} ({status})"


def _generate_step_up_code() -> str:
    """Six digits, uniformly distributed. `secrets.randbelow` rather than
    `token_hex` so the code is typeable on a phone keypad."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_step_up_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class StepUpChallenge(models.Model):
    """A pending re-confirmation for one destructive action (PG-203).

    Sudo mode, not a second login: the session stays exactly as it is and the
    user proves presence once, in an overlay. That replaces the sign-out and
    sign-back-in dance the owner transfer would otherwise have needed, which
    proved nothing a fresh challenge does not.

    Two proof methods, chosen by what the account already has:

    * `TOTP` -- the authenticator app. We cannot check the code ourselves,
      Supabase holds the secret, so the *backend* forwards the user's own JWT
      to Supabase's factors API and verifies there. Doing it server-side (not
      from the browser) is the whole point: a dialog the frontend can skip is
      decoration.
    * `EMAIL` -- a six-digit code we generate and mail. Only the hash is
      stored, so a database read cannot complete somebody else's confirmation.

    Deliberately NOT keyed off the JWT's `aal` claim. A token refresh keeps
    `aal2` while proving nothing fresh, so "session is aal2" would have made
    this security theatre for exactly the accounts that enabled MFA.
    """

    class Purpose(models.TextChoices):
        DELETE_ACCOUNT = "delete_account", "Delete account"
        OWNER_TRANSFER = "owner_transfer", "Confirm owner transfer"

    class Method(models.TextChoices):
        TOTP = "totp", "Authenticator app"
        EMAIL = "email", "Emailed code"

    # How long a challenge can sit unanswered, and how many wrong guesses it
    # survives. Five attempts is enough for a fat-fingered keypad and far too
    # few to walk a six-digit space.
    TTL_SECONDS = 10 * 60
    MAX_ATTEMPTS = 5

    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="step_up_challenges"
    )
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    method = models.CharField(max_length=16, choices=Method.choices)
    # Empty for TOTP -- there is no code of ours to compare against.
    code_hash = models.CharField(max_length=64, blank=True)
    # Supabase's factor and challenge ids, for the TOTP path only.
    factor_id = models.CharField(max_length=64, blank=True)
    challenge_id = models.CharField(max_length=64, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user_profile", "purpose", "consumed_at"]),
        ]

    def __str__(self) -> str:
        return f"Step-up ({self.purpose}) for {self.user_profile.email}"


class StepUpGrant(models.Model):
    """Proof that a challenge was answered, handed to the client as an opaque
    token and spent on the next destructive call.

    Single use rather than a rolling sudo window. A window would let one
    confirmation authorise several destructive actions, and "I confirmed the
    owner transfer" should never silently also authorise "delete everything".
    Ten minutes is long enough to read a confirmation dialog properly.
    """

    TTL_SECONDS = 10 * 60

    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="step_up_grants"
    )
    purpose = models.CharField(max_length=32, choices=StepUpChallenge.Purpose.choices)
    # Only the hash -- the plaintext token exists solely in the response body
    # and the client's memory.
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["token_hash"]),
        ]

    def __str__(self) -> str:
        status = "spent" if self.consumed_at else "valid"
        return f"Step-up grant ({self.purpose}) for {self.user_profile.email} ({status})"


class Broadcast(models.Model):
    """A one-off announcement: an outage, a new tier, anything that is news
    rather than lifecycle.

    Separate from LifecycleEmailTemplate because the two answer different
    questions. A template is a *reusable* body fired by an event and edited
    over time; a broadcast is written once, sent once, and then becomes a
    record of what was said. Editing one after the fact would falsify that
    record, so a sent broadcast is frozen.

    Deliberately no open or click tracking. The point is a history of what
    went out and to how many people, not analytics on who read it.
    """

    class Audience(models.TextChoices):
        ALL = "all", "Everyone with an account"
        FOUNDING = "founding", "Founding Member only"
        SOLO = "solo", "Solo only"
        STUDIO = "studio", "Studio only"
        AGENCY = "agency", "Agency only"

    subject = models.CharField(max_length=255)
    body = models.TextField(
        help_text=(
            "Plain text, sent through the same branded wrapper as every other "
            "PayGlue email. No placeholders: a broadcast says the same thing to "
            "everyone, which is what makes it a broadcast."
        )
    )
    audience = models.CharField(
        max_length=16, choices=Audience.choices, default=Audience.ALL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Set together, and only by the send action. Their presence is what marks
    # this broadcast as spent.
    sent_at = models.DateTimeField(null=True, blank=True)
    recipient_count = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        if self.sent_at:
            return f"{self.subject} (sent to {self.recipient_count} on {self.sent_at:%Y-%m-%d})"
        return f"{self.subject} (draft)"

    @property
    def is_sent(self) -> bool:
        return self.sent_at is not None

    def recipients(self) -> list[str]:
        """Owner email addresses for the chosen audience.

        Owners only: they are the account holders, and a team member added to
        somebody else's publication never asked us for product news.
        """
        accounts = BillingAccount.objects.select_related("owner", "plan")
        if self.audience != self.Audience.ALL:
            accounts = accounts.filter(plan__key=self.audience)
        return sorted({a.owner.email for a in accounts if a.owner.email})


class NewsletterRouting(models.Model):
    """Routes a Creem newsletter opt-in to PayGlue's own Ghost blog.

    PayGlue as its own customer: someone ticks the opt-in box at checkout, and
    the same machinery that syncs a customer's buyers into their Ghost becomes
    the thing that syncs our buyers into ours.

    Deliberately not a product mapping. Mappings are per product, and the
    opt-in sits on eleven of them; the rule that actually matters is "bought
    anything from this store, and ticked the box", so that is what this stores.

    A singleton in practice -- there is one PayGlue blog -- but kept as a
    normal model so it has an admin page, a health check and an audit trail
    instead of living in environment variables nobody can inspect.
    """

    # What Ghost sends the new member. "subscribe" is Ghost's newsletter
    # opt-in email: they only end up on the list after confirming, which is
    # what makes this a double opt-in rather than a bare checkbox.
    class GhostEmail(models.TextChoices):
        SUBSCRIBE = "subscribe", "Newsletter opt-in (double opt-in)"
        SIGNIN = "signin", "Magic link"
        SIGNUP = "signup", "Account confirmation"
        NONE = "", "No email"

    enabled = models.BooleanField(
        default=False,
        help_text="Off until the connection has passed a health check at least once.",
    )
    ghost_api_base_url = models.URLField(
        help_text="e.g. https://blog.payglue.io (no trailing path)"
    )
    ghost_admin_api_key_enc = models.TextField(
        blank=True, default="", help_text="Encrypted at rest, shown as dots once saved."
    )
    creem_store_id = models.CharField(
        max_length=64,
        default="sto_3MX9ng1a4C6U5PVWJVbuQm",
        help_text="Only checkouts from this store are considered.",
    )
    # Creem's product API spells this custom field key in snake_case while the
    # checkout payload spells it camelCase; the reader handles both, this is
    # just the key itself.
    optin_field_key = models.CharField(max_length=64, default="newsletteroptin")
    ghost_email_type = models.CharField(
        max_length=16, choices=GhostEmail.choices, default=GhostEmail.SUBSCRIBE
    )
    ghost_labels = models.CharField(
        max_length=255,
        default="payglue:client",
        help_text="Comma-separated Ghost labels, so our own customers stay filterable in the blog.",
    )

    last_health_check_at = models.DateTimeField(null=True, blank=True)
    last_health_ok = models.BooleanField(null=True, blank=True)
    last_health_detail = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Newsletter routing"
        verbose_name_plural = "Newsletter routing"

    def __str__(self) -> str:
        state = "on" if self.enabled else "off"
        return f"Newsletter routing to {self.ghost_api_base_url} ({state})"

    @property
    def labels(self) -> list[str]:
        return [lbl.strip() for lbl in self.ghost_labels.split(",") if lbl.strip()]


class SupportRequest(models.Model):
    """A support request raised from the dashboard, mirrored into Linear.

    We have no helpdesk, only André's inbox and Linear. Rather than pay for
    Linear Ask, every request opens an issue on the support team and keeps the
    identifier (PG-231 and so on) so both sides can name the same thing.

    Deliberately one-way: we push the request in and read the status back out.
    Replies still happen by email. Issue *content* is never exposed to the
    customer, because internal comments live on the same issue.
    """

    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE = "done"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_DONE, "Resolved"),
        (STATUS_CANCELLED, "Closed"),
    ]

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="support_requests"
    )
    email = models.EmailField()
    name = models.CharField(max_length=200, blank=True)
    topic = models.CharField(max_length=40, blank=True)
    message = models.TextField()

    # Blank when Linear was unreachable. The request is still stored and the
    # customer still gets a reply, they just have no reference number.
    linear_issue_id = models.CharField(max_length=64, blank=True)
    linear_identifier = models.CharField(max_length=32, blank=True, db_index=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    status_synced_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.linear_identifier or 'unfiled'} from {self.email}"

    @property
    def reference(self) -> str:
        """What the customer is told to quote. Falls back to our own id so a
        Linear outage still leaves something to search for."""
        return self.linear_identifier or f"PG-REQ-{self.pk}"


class FoundingSale(models.Model):
    """One claimed founding-member spot, keyed by Creem's order id.

    Exists for idempotency. Creem retries webhooks, and without a record of
    which orders were already counted, a retry would burn a second spot and
    walk the price ladder forward early.

    Also doubles as the local record of who bought in at which tier, which
    the pricing_tiers table (a counter, not a ledger) cannot tell us.
    """

    order_id = models.CharField(max_length=128, unique=True)
    product_id = models.CharField(max_length=128)
    email = models.EmailField(blank=True)
    # Null when the product matched no tier, i.e. not a founding purchase.
    tier = models.PositiveSmallIntegerField(null=True, blank=True)
    # The rate as it stood at purchase, in cents. Captured rather than looked
    # up later, because editing a tier's price must never rewrite what an
    # existing member was promised for life.
    price_cents = models.PositiveIntegerField(null=True, blank=True)
    # False when the tier had already sold out, i.e. somebody bought through an
    # old checkout link. Creem enforces no quantity limit, so this is the only
    # place such a purchase becomes visible.
    tier_was_active = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.order_id} (tier {self.tier or 'none'})"

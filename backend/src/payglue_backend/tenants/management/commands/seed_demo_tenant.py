# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Seed a fully populated "demo" tenant for webinars and screenshots.

Idempotent: does nothing if a tenant with slug "demo" already exists, so
it's safe to invoke from scripts/predeploy.sh on every deploy. Re-run with
--reset to wipe and rebuild the demo tenant's business data (the owner
login itself is left untouched once created).
"""
import secrets
from datetime import timedelta

import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from payglue_backend.tenants.models import (
    BillingProfile,
    PublicAuditEvent,
    Tenant,
    TenantMembership,
    UserProfile,
)
from payglue_backend.tenants.supabase_admin import (
    SupabaseAdminError,
    create_supabase_user,
    get_supabase_user_by_email,
    update_supabase_user_password,
)
from payglue_backend.webhooks.models import (
    BuyButton,
    IntegrationConfig,
    PaywallConfig,
    PricingTable,
    PricingTier,
    ProductMapping,
    WebhookInboundEvent,
)

DEMO_SLUG = "demo"
DEMO_OWNER_EMAIL = "demo@payglue.io"


class Command(BaseCommand):
    help = "Seed a fully populated demo tenant for webinars/screenshots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Wipe and rebuild the demo tenant's business data (keeps the owner login).",
        )

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(slug=DEMO_SLUG).first()

        if tenant and not options["reset"]:
            self.stdout.write(self.style.WARNING(f"Tenant '{DEMO_SLUG}' already exists, skipping. Use --reset to rebuild its data."))
            return

        if not tenant:
            tenant, password = self._create_tenant_and_owner()
            self.stdout.write(self.style.SUCCESS(f"Created demo tenant '{DEMO_SLUG}' owned by {DEMO_OWNER_EMAIL}"))
            self.stdout.write(self.style.SUCCESS(f"Login: {DEMO_OWNER_EMAIL} / {password}"))
        else:
            self._wipe_business_data(tenant)
            self.stdout.write(self.style.SUCCESS(f"Reset business data for existing demo tenant '{DEMO_SLUG}'"))

        with transaction.atomic():
            owner_membership = TenantMembership.objects.get(tenant=tenant, role=TenantMembership.Role.OWNER)
            self._seed_team(tenant)
            self._seed_billing(tenant)
            self._seed_integrations(tenant)
            self._seed_mappings(tenant)
            self._seed_webhook_events(tenant)
            self._seed_audit_events(tenant, owner_membership)
            self._seed_buy_buttons(tenant)
            self._seed_paywall(tenant)
            self._seed_pricing_table(tenant)

        self.stdout.write(self.style.SUCCESS(f"Demo tenant '{DEMO_SLUG}' fully seeded."))

    # -- setup -----------------------------------------------------------

    def _create_tenant_and_owner(self):
        password = secrets.token_urlsafe(10)
        try:
            supabase_user_id = create_supabase_user(DEMO_OWNER_EMAIL, password)
        except SupabaseAdminError as exc:
            if "email_exists" not in str(exc):
                self.stdout.write(self.style.ERROR(f"Could not create Supabase user, aborting: {exc}"))
                raise
            supabase_user_id = get_supabase_user_by_email(DEMO_OWNER_EMAIL)
            if not supabase_user_id:
                self.stdout.write(self.style.ERROR(f"Supabase reports {DEMO_OWNER_EMAIL} exists but lookup found nothing, aborting."))
                raise
            update_supabase_user_password(supabase_user_id, password)
            self.stdout.write(self.style.WARNING(f"{DEMO_OWNER_EMAIL} already existed in Supabase, reset its password instead."))

        profile, _ = UserProfile.objects.get_or_create(
            firebase_uid=supabase_user_id, defaults={"email": DEMO_OWNER_EMAIL}
        )
        tenant = Tenant(slug=DEMO_SLUG, schema_name=DEMO_SLUG)
        tenant.full_clean()
        tenant.save()
        TenantMembership.objects.create(tenant=tenant, user_profile=profile, role=TenantMembership.Role.OWNER)
        return tenant, password

    def _wipe_business_data(self, tenant):
        WebhookInboundEvent.objects.filter(tenant_slug=tenant.slug).delete()
        ProductMapping.objects.filter(tenant_slug=tenant.slug).delete()
        IntegrationConfig.objects.filter(tenant_slug=tenant.slug).delete()
        # Credentials are tenant_slug-linked with no ForeignKey, so nothing
        # else removes them -- a --reset that left them behind would rebuild
        # the demo on top of stale secrets.
        from payglue_backend.webhooks.models import TenantProviderCredential

        TenantProviderCredential.objects.filter(tenant_slug=tenant.slug).delete()
        BuyButton.objects.filter(tenant_slug=tenant.slug).delete()
        PaywallConfig.objects.filter(tenant_slug=tenant.slug).delete()
        PricingTable.objects.filter(tenant_slug=tenant.slug).delete()
        PublicAuditEvent.objects.filter(tenant=tenant).delete()
        TenantMembership.objects.filter(tenant=tenant).exclude(role=TenantMembership.Role.OWNER).delete()

    # -- seeders -----------------------------------------------------------

    def _seed_team(self, tenant):
        fake_members = [
            ("sarah@northwind.press", "admin"),
            ("marco@northwind.press", "support_readonly"),
        ]
        for email, role in fake_members:
            profile, _ = UserProfile.objects.get_or_create(
                email=email, defaults={"firebase_uid": f"demo-{secrets.token_hex(8)}"}
            )
            TenantMembership.objects.get_or_create(tenant=tenant, user_profile=profile, defaults={"role": role})

    def _seed_billing(self, tenant):
        BillingProfile.objects.update_or_create(
            tenant=tenant,
            defaults={
                "legal_name": "Northwind Press GmbH",
                "billing_email": "billing@northwind.press",
                "country_code": "DE",
                "tax_id": "DE123456789",
            },
        )

    # Plausible-looking but obviously fake values. The demo tenant exists for
    # screenshots and webinars, so the connection pages have to look filled in
    # -- an empty Ghost card photographs like a broken product. Nothing here
    # reaches a real service: the tokens are visibly demo strings, and Ghost
    # points at demo.payglue.io.
    DEMO_CREDENTIALS = {
        "cms": {
            "api_base_url": "https://demo.payglue.io",
            "admin_api_key": "6f1e9c0b2a7d4e8f3b5c1a90:"
            + "d4c3b2a1908f7e6d5c4b3a2918f7e6d5c4b3a2918f7e6d5c4b3a2918f7e6d5c4b",
        },
        "polar": {
            "api_key": "polar_oat_DEMOxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "webhook_secret": "whsec_demo_polar_0000000000",
        },
        "paypal": {
            "client_id": "AeDEMOclientid0000000000000000000000000000000000",
            "client_secret": "EDEMOsecret000000000000000000000000000000000000",
        },
        "lemonsqueezy": {
            "api_key": "lsq_demo_0000000000000000000000000000000000000000",
            "signing_secret": "demo_lemonsqueezy_signing_secret",
        },
    }

    def _seed_integrations(self, tenant):
        from payglue_backend.webhooks.credentials import FernetCipher
        from payglue_backend.webhooks.models import TenantProviderCredential

        connected = ["ghost", "polar", "paypal", "lemonsqueezy"]
        cipher = FernetCipher()
        for key in connected:
            provider_key = "cms" if key == "ghost" else key
            IntegrationConfig.objects.update_or_create(
                tenant_slug=tenant.slug,
                provider_key=provider_key,
                defaults={"enabled": True, "provider_type": key, "metadata": {}},
            )
            # Without this the connection detail page renders an empty form and
            # the Connections overview shows the provider as unconfigured, which
            # is exactly what the demo is meant to show working.
            credentials = self.DEMO_CREDENTIALS.get(provider_key)
            if credentials:
                TenantProviderCredential.objects.update_or_create(
                    tenant_slug=tenant.slug,
                    provider_key=provider_key,
                    defaults={"credentials_enc": cipher.encrypt(json.dumps(credentials))},
                )

    def _seed_mappings(self, tenant):
        rows = [
            ("polar", "order.paid", "founding-member", "founding_member", "grant"),
            ("polar", "subscription.canceled", "founding-member", "founding_member", "revoke"),
            ("lemonsqueezy", "order.paid", "pro-monthly", "pro", "grant"),
            ("paypal", "order.paid", "deep-dive-report", "free_comped", "grant"),
        ]
        for provider, event_type, product_id, entitlement, action in rows:
            ProductMapping.objects.get_or_create(
                tenant_slug=tenant.slug,
                payment_provider=provider,
                event_type=event_type,
                external_product_id=product_id,
                defaults={
                    "entitlement_key": entitlement,
                    "action": action,
                    "quantity": 1,
                    "is_active": True,
                    "metadata": {"ghost_subscribed": True, "ghost_email_types": ["signin"], "source_type": "button", "source_name": "Demo"},
                },
            )

    def _seed_webhook_events(self, tenant):
        now = timezone.now()
        samples = [
            ("polar", WebhookInboundEvent.Status.PROCESSED, 0),
            ("polar", WebhookInboundEvent.Status.PROCESSED, 1),
            ("lemonsqueezy", WebhookInboundEvent.Status.PROCESSED, 2),
            ("paypal", WebhookInboundEvent.Status.PROCESSED, 3),
            ("polar", WebhookInboundEvent.Status.PROCESSED, 5),
            ("lemonsqueezy", WebhookInboundEvent.Status.FAILED, 6),
            ("polar", WebhookInboundEvent.Status.PROCESSED, 8),
            ("paypal", WebhookInboundEvent.Status.PROCESSED, 9),
            ("polar", WebhookInboundEvent.Status.PROCESSED, 11),
            ("lemonsqueezy", WebhookInboundEvent.Status.PROCESSED, 13),
        ]
        for provider, status, days_ago in samples:
            hours_ago = days_ago * 24 + secrets.randbelow(20)
            created_at = now - timedelta(hours=hours_ago)
            event = WebhookInboundEvent.objects.create(
                tenant_slug=tenant.slug,
                provider=provider,
                status=status,
                attempts=1 if status == WebhookInboundEvent.Status.PROCESSED else 3,
                payload_raw=b'{"demo": true}',
                payload_snapshot={"type": "order.paid", "demo": True},
                headers_snapshot={},
                endpoint_path=f"/t/{tenant.slug}/webhooks/{provider}/[redacted]/",
                endpoint_metadata={"method": "POST", "content_type": "application/json"},
                processed_at=created_at if status == WebhookInboundEvent.Status.PROCESSED else None,
                failed_at=created_at if status == WebhookInboundEvent.Status.FAILED else None,
                last_error="" if status == WebhookInboundEvent.Status.PROCESSED else "Timed out contacting Ghost Admin API",
            )
            WebhookInboundEvent.objects.filter(pk=event.pk).update(created_at=created_at, updated_at=created_at)

    def _seed_audit_events(self, tenant, owner_membership):
        now = timezone.now()
        rows = [
            (PublicAuditEvent.EventType.TEAM_MEMBER_CREATED, "user_profile", 12),
            (PublicAuditEvent.EventType.INTEGRATION_CREDENTIALS_WRITTEN, "integration_config", 9),
            (PublicAuditEvent.EventType.BILLING_PROFILE_UPDATED, "billing_profile", 5),
            (PublicAuditEvent.EventType.EVENT_REPLAY_REQUESTED, "webhook_inbound_event", 1),
        ]
        for event_type, target_type, days_ago in rows:
            event = PublicAuditEvent.objects.create(
                tenant=tenant,
                actor_membership=owner_membership,
                event_type=event_type,
                target_type=target_type,
                target_id=secrets.token_hex(6),
                metadata={},
            )
            created_at = now - timedelta(days=days_ago)
            PublicAuditEvent.objects.filter(pk=event.pk).update(created_at=created_at)

    def _seed_buy_buttons(self, tenant):
        BuyButton.objects.get_or_create(
            tenant_slug=tenant.slug,
            name="Founding Member",
            defaults={
                "id": secrets.token_urlsafe(12),
                "label": "Become a Founding Member",
                "description": "Lifetime access, lock in the lowest price forever.",
                "target_url": "https://polar.sh/northwind/founding-member",
                "bg_color": "#4f46e5",
                "text_color": "#ffffff",
            },
        )
        BuyButton.objects.get_or_create(
            tenant_slug=tenant.slug,
            name="Pro Monthly",
            defaults={
                "id": secrets.token_urlsafe(12),
                "label": "Subscribe monthly",
                "description": "Full archive access, cancel anytime.",
                "target_url": "https://northwind.lemonsqueezy.com/checkout/pro-monthly",
                "bg_color": "#0ea5e9",
                "text_color": "#ffffff",
            },
        )

    def _seed_paywall(self, tenant):
        PaywallConfig.objects.get_or_create(
            tenant_slug=tenant.slug,
            name="Deep Dive Articles",
            defaults={
                "id": secrets.token_urlsafe(12),
                "product_id": "deep-dive-report",
                "product_name": "Deep Dive Report",
                "headline": "This is a Deep Dive",
                "body": "Deep Dives are our longest, most researched pieces. Purchase this one, or become a member for full access.",
                "button_text": "Unlock this Deep Dive",
                "button_url": "https://paypal.me/northwindpress/12",
            },
        )

    def _seed_pricing_table(self, tenant):
        table, _ = PricingTable.objects.get_or_create(
            tenant_slug=tenant.slug,
            name="Northwind Press Membership",
            defaults={"id": secrets.token_urlsafe(12), "template": PricingTable.Template.CLASSIC, "show_toggle": True, "accent_color": "#4f46e5", "currency": "EUR"},
        )
        if table.tiers.exists():
            return
        tiers = [
            {
                "id": secrets.token_urlsafe(12), "table": table, "position": 0, "name": "Free",
                "description": "Weekly newsletter, no card required.",
                "price_monthly": "0", "price_yearly": "0",
                "cta_type": PricingTier.CtaType.FREE_SIGNUP, "cta_label": "Sign up free",
                "features": ["Weekly newsletter", "Public articles", "Comment on posts"],
            },
            {
                "id": secrets.token_urlsafe(12), "table": table, "position": 1, "name": "Pro",
                "description": "Full archive, deep dives included.",
                "price_monthly": "9", "price_yearly": "90", "highlight": True, "ribbon_text": "Popular",
                "cta_type": PricingTier.CtaType.SUBSCRIPTION, "cta_label": "Subscribe",
                "cta_url": "https://northwind.lemonsqueezy.com/checkout/pro-monthly",
                "features": ["Everything in Free", "Full article archive", "Monthly deep dives", "Ad-free reading"],
            },
            {
                "id": secrets.token_urlsafe(12), "table": table, "position": 2, "name": "Founding Member",
                "description": "Lifetime price lock, our biggest supporters.",
                "price_monthly": "19", "price_yearly": "190",
                "cta_type": PricingTier.CtaType.ONE_TIME, "cta_label": "Become a Founder",
                "cta_url": "https://polar.sh/northwind/founding-member",
                "features": ["Everything in Pro", "Lifetime price lock", "Founding Member badge", "Priority replies"],
            },
        ]
        PricingTier.objects.bulk_create([PricingTier(**t) for t in tiers])

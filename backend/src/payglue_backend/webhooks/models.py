# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import models


class WebhookEventRecord(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "processing"
        PROCESSED = "processed", "processed"
        RELEASED = "released", "released"

    idempotency_key = models.CharField(max_length=255, unique=True)
    tenant_slug = models.CharField(max_length=64)
    provider = models.CharField(max_length=64)
    provider_event_id = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=Status.choices)
    started_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_slug", "provider", "provider_event_id"], name="webhooks_we_tenant__38a532_idx"),
            models.Index(fields=["status"], name="webhooks_we_status_36772e_idx"),
        ]


class WebhookInboundEvent(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "received", "received"
        PROCESSING = "processing", "processing"
        PROCESSED = "processed", "processed"
        SKIPPED = "skipped", "skipped"
        FAILED = "failed", "failed"
        DEAD_LETTER = "dead_letter", "dead_letter"

    tenant_slug = models.CharField(max_length=64)
    provider = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    payload_raw = models.BinaryField()
    payload_snapshot = models.JSONField(null=True, blank=True)
    headers_snapshot = models.JSONField(default=dict)
    endpoint_path = models.CharField(max_length=255)
    endpoint_token_hash = models.CharField(max_length=64, blank=True, default="")
    endpoint_metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    dead_lettered_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_slug", "provider", "status"], name="webhooks_we_tenant__6d43d2_idx"),
            models.Index(fields=["status", "next_attempt_at"], name="webhooks_we_status_1ba0ac_idx"),
        ]


class IntegrationConfig(models.Model):
    tenant_slug = models.CharField(max_length=64)
    provider_key = models.CharField(max_length=32)
    enabled = models.BooleanField(default=False)
    provider_type = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_slug", "provider_key"],
                name="webhooks_unique_integration_per_tenant",
            )
        ]


class TenantProviderCredential(models.Model):
    tenant_slug = models.CharField(max_length=64)
    provider_key = models.CharField(max_length=64)
    credentials_enc = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_slug", "provider_key"],
                name="webhooks_unique_credential_per_tenant_provider",
            )
        ]
        indexes = [
            models.Index(fields=["tenant_slug", "provider_key"], name="webhooks_te_tenant__9770a6_idx"),
        ]


class PaywallConfig(models.Model):
    id = models.CharField(max_length=32, primary_key=True)
    tenant_slug = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    product_id = models.CharField(max_length=255, blank=True, default="")
    product_name = models.CharField(max_length=255, blank=True, default="")
    headline = models.CharField(max_length=255, default="Premium content")
    body = models.TextField(default="Purchase access to continue reading.")
    button_text = models.CharField(max_length=128, default="Get access")
    button_url = models.URLField(max_length=512, blank=True, default="")
    button_color = models.CharField(max_length=16, default="#4f46e5")
    text_color = models.CharField(max_length=16, default="#ffffff")
    border_radius = models.CharField(max_length=8, default="md")
    width = models.CharField(max_length=8, default="auto")
    alignment = models.CharField(max_length=8, default="left")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_slug", "created_at"], name="webhooks_pw_tenant__idx"),
        ]


class BuyButton(models.Model):
    class BorderRadius(models.TextChoices):
        NONE = "none", "none"
        MD = "md", "md"
        FULL = "full", "full"

    class Width(models.TextChoices):
        AUTO = "auto", "auto"
        FULL = "full", "full"

    class Alignment(models.TextChoices):
        LEFT = "left", "left"
        CENTER = "center", "center"
        RIGHT = "right", "right"

    class LinkTarget(models.TextChoices):
        BLANK = "_blank", "_blank"
        SELF = "_self", "_self"

    id = models.CharField(max_length=32, primary_key=True)
    tenant_slug = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    label = models.CharField(max_length=128, default="Buy now")
    description = models.TextField(blank=True, default="")
    target_url = models.URLField(max_length=512, blank=True, default="")
    target = models.CharField(max_length=8, choices=LinkTarget.choices, default=LinkTarget.BLANK)
    bg_color = models.CharField(max_length=16, default="#4f46e5")
    text_color = models.CharField(max_length=16, default="#ffffff")
    border_radius = models.CharField(max_length=8, choices=BorderRadius.choices, default=BorderRadius.MD)
    width = models.CharField(max_length=8, choices=Width.choices, default=Width.AUTO)
    alignment = models.CharField(max_length=8, choices=Alignment.choices, default=Alignment.LEFT)
    # Which provider product this button is linked to, persisted so the editor
    # restores "Link to a product" directly instead of guessing by matching
    # target_url against live product lists -- that guess raced product
    # loading and failed outright for Ko-fi/Gumroad on every re-edit.
    product_provider = models.CharField(max_length=32, blank=True, default="")
    product_id = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_slug", "created_at"], name="webhooks_bb_tenant__idx"),
        ]


class PricingTable(models.Model):
    class Template(models.TextChoices):
        CLASSIC = "classic", "classic"
        MINIMAL = "minimal", "minimal"
        BOLD = "bold", "bold"

    id = models.CharField(max_length=32, primary_key=True)
    tenant_slug = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    template = models.CharField(max_length=16, choices=Template.choices, default=Template.CLASSIC)
    show_toggle = models.BooleanField(default=False)
    accent_color = models.CharField(max_length=7, default="#4f46e5")
    currency = models.CharField(max_length=3, default="EUR")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_slug", "created_at"], name="webhooks_prt_tenant__idx"),
        ]


class PricingTier(models.Model):
    class CtaType(models.TextChoices):
        CUSTOM_URL = "custom_url", "custom_url"
        FREE_SIGNUP = "free_signup", "free_signup"
        ONE_TIME = "one_time", "one_time"
        SUBSCRIPTION = "subscription", "subscription"

    id = models.CharField(max_length=32, primary_key=True)
    table = models.ForeignKey(PricingTable, on_delete=models.CASCADE, related_name="tiers")
    position = models.IntegerField(default=0)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    price_monthly = models.CharField(max_length=64, blank=True, default="")
    price_yearly = models.CharField(max_length=64, blank=True, default="")
    trial_days = models.IntegerField(null=True, blank=True)
    highlight = models.BooleanField(default=False)
    ribbon_text = models.CharField(max_length=10, blank=True, default="")
    cta_type = models.CharField(max_length=16, choices=CtaType.choices, default=CtaType.CUSTOM_URL)
    cta_label = models.CharField(max_length=128, default="Get started")
    cta_url = models.CharField(max_length=512, blank=True, default="")
    features = models.JSONField(default=list)
    # Which provider product this tier is linked to, persisted so the editor
    # restores "Link to a product" directly instead of guessing by matching
    # cta_url against live product lists -- same fix as BuyButton (527d75d),
    # needed here too since that guess never worked for Ko-fi.
    product_provider = models.CharField(max_length=32, blank=True, default="")
    product_id = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position"]


class ProductMapping(models.Model):
    class Action(models.TextChoices):
        GRANT = "grant", "grant"
        REVOKE = "revoke", "revoke"

    tenant_slug = models.CharField(max_length=64)
    payment_provider = models.CharField(max_length=64)
    event_type = models.CharField(max_length=128)
    external_product_id = models.CharField(max_length=128)
    entitlement_key = models.CharField(max_length=128)
    action = models.CharField(max_length=32, choices=Action.choices)
    quantity = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "tenant_slug",
                    "payment_provider",
                    "event_type",
                    "external_product_id",
                    "entitlement_key",
                    "action",
                ],
                name="webhooks_unique_product_mapping_rule",
            )
        ]
        indexes = [
            models.Index(fields=["tenant_slug", "payment_provider", "event_type", "is_active"], name="webhooks_pr_tenant__c747b0_idx"),
            models.Index(fields=["tenant_slug", "external_product_id", "is_active"], name="webhooks_pr_tenant__3cff07_idx"),
        ]

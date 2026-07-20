// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

export interface SessionUser {
  id: number
  firebase_uid: string
  email: string
}

export interface TenantMembership {
  tenant_slug: string
  role: 'owner' | 'admin' | 'billing_admin' | 'support_readonly'
  status: 'active' | 'suspended' | 'disabled' | 'paused'
}

export interface SessionBillingInfo {
  plan: string
  downgrade_detected_at: string | null
  grace_period_ends_at: string | null
}

export interface AuthSessionResponse {
  user: SessionUser
  memberships: TenantMembership[]
  billing: SessionBillingInfo | null
}

export interface TenantCreateResponse {
  tenant_slug: string
}

export interface ProductMappingMetadata {
  ghost_subscribed?: boolean
  ghost_email_types?: Array<'signup' | 'signin' | 'subscribe'>
  ghost_email_type?: 'signup' | 'signin' | 'subscribe' | null
  ghost_labels?: string[]
  source_type?: string
  source_name?: string
  source_tier?: string
}

export interface ProductMapping {
  id: number
  payment_provider: string
  event_type: string
  external_product_id: string
  entitlement_key: string
  action: 'grant' | 'revoke'
  quantity: number
  is_active: boolean
  metadata: ProductMappingMetadata
}

export interface TeamMember {
  id: number
  email: string
  firebase_uid: string
  role: TenantMembership['role']
  created_at: string
  updated_at: string
  /** True when adding this member provisioned a brand-new PayGlue account and sent them a sign-in email. */
  invited_new_account?: boolean
}

export interface PricingPlan {
  id: string
  name: string
  price: string
  description: string
  features: string[]
  ctaLabel: string
  entitlementKey: string
}

export type PricingFeatureIcon = 'check' | 'dot' | 'dash' | 'none'

export interface PricingFeature {
  text: string
  icon: PricingFeatureIcon
}

export interface PricingTierData {
  id?: string
  position?: number
  name: string
  description: string
  price_monthly: string
  price_yearly: string
  trial_days: number | null
  highlight: boolean
  ribbon_text: string
  cta_type: 'custom_url' | 'free_signup' | 'one_time' | 'subscription'
  cta_label: string
  cta_url: string
  features: PricingFeature[]
  product_provider?: string
  product_id?: string
}

export interface PricingTableData {
  id: string
  name: string
  template: 'classic' | 'minimal' | 'bold'
  show_toggle: boolean
  accent_color: string
  currency: string
  tiers: PricingTierData[]
  created_at: string
  updated_at: string
}

export interface IntegrationConfig {
  provider_key: 'polar' | 'lemonsqueezy' | 'paypal' | 'gumroad' | 'paddle' | 'kofi' | 'creem' | 'patreon' | 'cms'
  enabled: boolean
  provider_type: string
  metadata: Record<string, unknown>
}

export interface IntegrationCredentialWriteResult {
  provider_key: 'polar' | 'lemonsqueezy' | 'paypal' | 'gumroad' | 'paddle' | 'kofi' | 'creem' | 'patreon' | 'cms'
  provider_type: string
  credential_ref: {
    backend: string
    masked_keys: string[]
    updated_at?: string
  }
  webhook_registration?: {
    registered: string[]
    failed: string[]
  }
}

export interface IntegrationHealthStatus {
  ok: boolean
  code: string
  message: string
  checked_at: string
}

export interface WebhookEvent {
  id: number
  tenant_slug: string
  provider: string
  status: 'received' | 'processing' | 'processed' | 'skipped' | 'failed' | 'dead_letter'
  attempts: number
  next_attempt_at: string | null
  last_error: string
  endpoint_path: string
  endpoint_metadata: Record<string, unknown>
  payload_snapshot: Record<string, unknown>
  headers_snapshot: Record<string, unknown>
  created_at: string
  updated_at: string
  dead_lettered_at: string | null
}

export interface ReplayWebhookEventResult {
  status: 'accepted'
  tracking_id: number
}

export interface AuditEvent {
  id: number
  event_type: string
  target_type: string
  target_id: string
  actor_membership_id: number | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface BillingProfile {
  legal_name: string
  billing_email: string
  country_code: string
  tax_id: string
}

export interface ServicePin {
  code: string
  created_at: string
  expires_at: string
  revoked_at: string | null
}

export interface SupportRequestSummary {
  id: number
  reference: string
  topic: string
  status: 'open' | 'in_progress' | 'done' | 'cancelled'
  status_label: string
  created_at: string
}

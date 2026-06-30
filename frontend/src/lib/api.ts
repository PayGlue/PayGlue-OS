// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import axios, { AxiosError } from 'axios'
import type {
  AuditEvent,
  BillingProfile,
  AuthSessionResponse,
  InvitationValidationResponse,
  IntegrationConfig,
  IntegrationCredentialWriteResult,
  IntegrationHealthStatus,
  PricingTableData,
  PricingTierData,
  ProductMapping,
  ReplayWebhookEventResult,
  TeamMember,
  TenantCreateResponse,
  TenantMembership,
  WebhookEvent,
} from '../types/api'

const baseURL = import.meta.env.VITE_API_BASE_URL ?? ''

export const api = axios.create({
  baseURL,
  timeout: 15000,
  withCredentials: false,
})

let onAuthError: (() => void) | null = null

export const setAuthErrorHandler = (handler: (() => void) | null) => {
  onAuthError = handler
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const status = error.response?.status
    if (status === 401) {
      onAuthError?.()
    }
    return Promise.reject(error)
  },
)

export class ApiHttpError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const extractApiError = (error: unknown): ApiHttpError => {
  if (error instanceof AxiosError) {
    const status = error.response?.status ?? 500
    const payload = error.response?.data as
      | { detail?: unknown; [key: string]: unknown }
      | undefined
    let detail = error.message
    if (typeof payload?.detail === 'string') {
      detail = payload.detail
    } else if (payload && typeof payload === 'object') {
      const flattened = Object.entries(payload)
        .flatMap(([key, value]) => {
          if (Array.isArray(value)) {
            return value.map((item) => `${key}: ${String(item)}`)
          }
          if (typeof value === 'string') {
            return [`${key}: ${value}`]
          }
          return []
        })
        .join('; ')
      if (flattened) {
        detail = flattened
      }
    }
    return new ApiHttpError(detail, status)
  }
  return new ApiHttpError('Unexpected API error', 500)
}

const isLikelyNetworkError = (error: AxiosError): boolean => {
  return (
    error.code === AxiosError.ERR_NETWORK ||
    (error.message === 'Network Error' && error.response == null)
  )
}

const toActionableApiError = (error: unknown): ApiHttpError => {
  if (error instanceof AxiosError && isLikelyNetworkError(error)) {
    return new ApiHttpError(
      'Unable to reach backend API from frontend. Check VITE_API_BASE_URL/proxy and backend availability.',
      0,
    )
  }
  return extractApiError(error)
}

export const postAuthSession = async (idToken: string): Promise<AuthSessionResponse> => {
  try {
    const { data } = await api.post<AuthSessionResponse>('/api/v1/auth/session', null, {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const validateInvitationCode = async (
  payload: { email: string; invitationCode: string },
): Promise<InvitationValidationResponse> => {
  try {
    const { data } = await api.post<InvitationValidationResponse>(
      '/api/v1/auth/invitation/validate',
      {
        email: payload.email,
        invitation_code: payload.invitationCode,
      },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const createTenant = async (
  idToken: string,
  payload: { slug: string },
): Promise<TenantCreateResponse> => {
  try {
    const { data } = await api.post<TenantCreateResponse>('/api/v1/tenants', payload, {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const updateTenant = async (
  tenantSlug: string,
  idToken: string,
  payload: { slug?: string },
): Promise<{ slug: string }> => {
  try {
    const { data } = await api.patch<{ slug: string }>(`/api/v1/tenants/${tenantSlug}`, payload, {
      headers: { Authorization: `Bearer ${idToken}` },
    })
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const deleteTenant = async (tenantSlug: string, idToken: string): Promise<void> => {
  try {
    await api.delete(`/api/v1/tenants/${tenantSlug}`, {
      headers: { Authorization: `Bearer ${idToken}` },
    })
  } catch (error) {
    throw toActionableApiError(error)
  }
}

const tenantPath = (tenantSlug: string, suffix: string): string =>
  `/t/${tenantSlug}/api/v1/${suffix}`

export const listMappings = async (
  tenantSlug: string,
  idToken: string,
): Promise<ProductMapping[]> => {
  try {
    const { data } = await api.get<ProductMapping[]>(tenantPath(tenantSlug, 'mappings'), {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export type ProductMappingPayload = Omit<ProductMapping, 'id'> & { metadata?: ProductMapping['metadata'] }

export const createMapping = async (
  tenantSlug: string,
  idToken: string,
  payload: ProductMappingPayload,
): Promise<ProductMapping> => {
  try {
    const { data } = await api.post<ProductMapping>(tenantPath(tenantSlug, 'mappings'), payload, {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const updateMapping = async (
  tenantSlug: string,
  idToken: string,
  mappingId: number,
  payload: Partial<ProductMappingPayload>,
): Promise<ProductMapping> => {
  try {
    const { data } = await api.patch<ProductMapping>(
      tenantPath(tenantSlug, `mappings?mapping_id=${mappingId}`),
      payload,
      { headers: { Authorization: `Bearer ${idToken}` } },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const deleteMapping = async (
  tenantSlug: string,
  idToken: string,
  mappingId: number,
): Promise<void> => {
  try {
    await api.delete(tenantPath(tenantSlug, `mappings?mapping_id=${mappingId}`), {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const listTeamMembers = async (
  tenantSlug: string,
  idToken: string,
): Promise<TeamMember[]> => {
  try {
    const { data } = await api.get<TeamMember[]>(tenantPath(tenantSlug, 'team'), {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const addTeamMember = async (
  tenantSlug: string,
  idToken: string,
  payload: { email?: string; firebase_uid?: string; role: TenantMembership['role'] },
): Promise<TeamMember> => {
  try {
    const { data } = await api.post<TeamMember>(tenantPath(tenantSlug, 'team'), payload, {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const updateTeamMemberRole = async (
  tenantSlug: string,
  idToken: string,
  membershipId: number,
  role: TenantMembership['role'],
): Promise<TeamMember> => {
  try {
    const { data } = await api.patch<TeamMember>(
      tenantPath(tenantSlug, `team/${membershipId}`),
      { role },
      {
        headers: {
          Authorization: `Bearer ${idToken}`,
        },
      },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const removeTeamMember = async (
  tenantSlug: string,
  idToken: string,
  membershipId: number,
): Promise<void> => {
  try {
    await api.delete(tenantPath(tenantSlug, `team/${membershipId}`), {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const getIntegrationConfig = async (
  tenantSlug: string,
  idToken: string,
  providerKey: 'payment' | 'cms',
): Promise<IntegrationConfig> => {
  try {
    const { data } = await api.get<IntegrationConfig>(
      tenantPath(tenantSlug, `integrations/${providerKey}`),
      {
        headers: {
          Authorization: `Bearer ${idToken}`,
        },
      },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const updateIntegrationConfig = async (
  tenantSlug: string,
  idToken: string,
  providerKey: 'payment' | 'cms',
  payload: Pick<IntegrationConfig, 'enabled' | 'provider_type' | 'metadata'>,
): Promise<IntegrationConfig> => {
  try {
    const { data } = await api.put<IntegrationConfig>(
      tenantPath(tenantSlug, `integrations/${providerKey}`),
      payload,
      {
        headers: {
          Authorization: `Bearer ${idToken}`,
        },
      },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const setIntegrationCredentials = async (
  tenantSlug: string,
  idToken: string,
  providerKey: 'payment' | 'cms',
  credentials: Record<string, string>,
): Promise<IntegrationCredentialWriteResult> => {
  try {
    const { data } = await api.put<IntegrationCredentialWriteResult>(
      tenantPath(tenantSlug, `integrations/${providerKey}/credentials`),
      { credentials },
      {
        headers: {
          Authorization: `Bearer ${idToken}`,
        },
      },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const runIntegrationHealthCheck = async (
  tenantSlug: string,
  idToken: string,
  providerKey: 'payment' | 'cms',
): Promise<IntegrationHealthStatus> => {
  try {
    const { data } = await api.get<IntegrationHealthStatus>(
      tenantPath(tenantSlug, `integrations/${providerKey}/health`),
      {
        headers: {
          Authorization: `Bearer ${idToken}`,
        },
      },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const getGhostStripeStatus = async (
  tenantSlug: string,
  idToken: string,
): Promise<{ connected: boolean; display_name?: string | null; error?: string }> => {
  try {
    const { data } = await api.get(
      tenantPath(tenantSlug, 'integrations/cms/ghost-stripe-status'),
      { headers: { Authorization: `Bearer ${idToken}` } },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const listWebhookEvents = async (
  tenantSlug: string,
  idToken: string,
): Promise<WebhookEvent[]> => {
  try {
    const { data } = await api.get<WebhookEvent[]>(tenantPath(tenantSlug, 'events'), {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const replayWebhookEvent = async (
  tenantSlug: string,
  idToken: string,
  eventId: number,
): Promise<ReplayWebhookEventResult> => {
  try {
    const { data } = await api.post<ReplayWebhookEventResult>(
      tenantPath(tenantSlug, `events/${eventId}/replay`),
      null,
      {
        headers: {
          Authorization: `Bearer ${idToken}`,
        },
      },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export interface AuditEventFilters {
  event_type?: string
  target_type?: string
  created_at_from?: string
  created_at_to?: string
}

export const listAuditEvents = async (
  tenantSlug: string,
  idToken: string,
  filters?: AuditEventFilters,
): Promise<AuditEvent[]> => {
  try {
    const { data } = await api.get<AuditEvent[]>(tenantPath(tenantSlug, 'events/audit'), {
      params: filters,
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const getBillingProfile = async (
  tenantSlug: string,
  idToken: string,
): Promise<BillingProfile> => {
  try {
    const { data } = await api.get<BillingProfile>(tenantPath(tenantSlug, 'billing'), {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export type BillingProfilePayload = BillingProfile

export const updateBillingProfile = async (
  tenantSlug: string,
  idToken: string,
  payload: BillingProfilePayload,
): Promise<BillingProfile> => {
  try {
    const { data } = await api.put<BillingProfile>(tenantPath(tenantSlug, 'billing'), payload, {
      headers: {
        Authorization: `Bearer ${idToken}`,
      },
    })
    return data
  } catch (error) {
    throw extractApiError(error)
  }
}

export const getPolarSubscriptions = async (
  tenantSlug: string,
  idToken: string,
): Promise<{ subscriptions: Record<string, unknown>[] }> => {
  try {
    const { data } = await api.get<{ subscriptions: Record<string, unknown>[] }>(
      tenantPath(tenantSlug, 'billing/subscription'),
      { headers: { Authorization: `Bearer ${idToken}` } },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const cancelPolarSubscription = async (
  tenantSlug: string,
  idToken: string,
  subscriptionId: string,
  sandbox = false,
): Promise<Record<string, unknown>> => {
  try {
    const { data } = await api.post<Record<string, unknown>>(
      tenantPath(tenantSlug, 'billing/subscription'),
      { subscription_id: subscriptionId, sandbox },
      { headers: { Authorization: `Bearer ${idToken}` } },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const getPolarInvoices = async (
  tenantSlug: string,
  idToken: string,
): Promise<{ invoices: Record<string, unknown>[] }> => {
  try {
    const { data } = await api.get<{ invoices: Record<string, unknown>[] }>(
      tenantPath(tenantSlug, 'billing/invoices'),
      { headers: { Authorization: `Bearer ${idToken}` } },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const getLemonSqueezyStores = async (
  tenantSlug: string,
  idToken: string,
): Promise<{ stores: { id: string; name: string; slug: string }[]; has_token: boolean; selected_store_id?: string; error?: string }> => {
  try {
    const { data } = await api.get<{ stores: { id: string; name: string; slug: string }[]; has_token: boolean; selected_store_id?: string; error?: string }>(
      tenantPath(tenantSlug, 'billing/lemonsqueezy-stores'),
      { headers: { Authorization: `Bearer ${idToken}` } },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const getLemonSqueezyProducts = async (
  tenantSlug: string,
  idToken: string,
): Promise<{ products: { id: string; name: string; checkout_url?: string }[]; has_token: boolean; needs_store?: boolean; error?: string }> => {
  try {
    const { data } = await api.get<{ products: { id: string; name: string; checkout_url?: string }[]; has_token: boolean; needs_store?: boolean; error?: string }>(
      tenantPath(tenantSlug, 'billing/lemonsqueezy-products'),
      { headers: { Authorization: `Bearer ${idToken}` } },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const getPayPalProducts = async (
  tenantSlug: string,
  idToken: string,
): Promise<{ products: { id: string; name: string }[]; has_token: boolean; error?: string }> => {
  try {
    const { data } = await api.get<{ products: { id: string; name: string }[]; has_token: boolean; error?: string }>(
      tenantPath(tenantSlug, 'billing/paypal-products'),
      { headers: { Authorization: `Bearer ${idToken}` } },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export const getPolarProducts = async (
  tenantSlug: string,
  idToken: string,
): Promise<{ products: { id: string; name: string; checkout_url?: string }[]; has_token: boolean; sandbox?: boolean; error?: string }> => {
  try {
    const { data } = await api.get<{ products: { id: string; name: string; checkout_url?: string }[]; has_token: boolean; sandbox?: boolean; error?: string }>(
      tenantPath(tenantSlug, 'billing/polar-products'),
      { headers: { Authorization: `Bearer ${idToken}` } },
    )
    return data
  } catch (error) {
    throw toActionableApiError(error)
  }
}

export interface PaywallConfigData {
  id: string
  name: string
  product_id: string
  product_name: string
  headline: string
  body: string
  button_text: string
  button_url: string
  button_color: string
  text_color: string
  border_radius: 'none' | 'md' | 'full'
  width: 'auto' | 'full'
  alignment: 'left' | 'center' | 'right'
  created_at: string
  updated_at: string
}

export const listPaywallConfigs = async (tenantSlug: string, idToken: string): Promise<PaywallConfigData[]> => {
  const { data } = await api.get<PaywallConfigData[]>(tenantPath(tenantSlug, 'paywalls'), {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  return data
}

export const createPaywallConfig = async (
  tenantSlug: string,
  idToken: string,
  payload: Omit<PaywallConfigData, 'id' | 'created_at' | 'updated_at'>,
): Promise<PaywallConfigData> => {
  const { data } = await api.post<PaywallConfigData>(tenantPath(tenantSlug, 'paywalls'), payload, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  return data
}

export const updatePaywallConfig = async (
  tenantSlug: string,
  idToken: string,
  id: string,
  payload: Partial<Omit<PaywallConfigData, 'id' | 'created_at' | 'updated_at'>>,
): Promise<PaywallConfigData> => {
  const { data } = await api.patch<PaywallConfigData>(tenantPath(tenantSlug, `paywalls/${id}`), payload, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  return data
}

export const deletePaywallConfig = async (tenantSlug: string, idToken: string, id: string): Promise<void> => {
  await api.delete(tenantPath(tenantSlug, `paywalls/${id}`), {
    headers: { Authorization: `Bearer ${idToken}` },
  })
}

export interface BuyButtonData {
  id: string
  name: string
  label: string
  description: string
  target_url: string
  target: '_blank' | '_self'
  bg_color: string
  text_color: string
  border_radius: 'none' | 'md' | 'full'
  width: 'auto' | 'full'
  alignment: 'left' | 'center' | 'right'
  created_at: string
  updated_at: string
}

export const listBuyButtons = async (tenantSlug: string, idToken: string): Promise<BuyButtonData[]> => {
  const { data } = await api.get<BuyButtonData[]>(tenantPath(tenantSlug, 'buttons'), {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  return data
}

export const createBuyButton = async (
  tenantSlug: string,
  idToken: string,
  payload: Omit<BuyButtonData, 'id' | 'created_at' | 'updated_at'>,
): Promise<BuyButtonData> => {
  const { data } = await api.post<BuyButtonData>(tenantPath(tenantSlug, 'buttons'), payload, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  return data
}

export const updateBuyButton = async (
  tenantSlug: string,
  idToken: string,
  id: string,
  payload: Partial<Omit<BuyButtonData, 'id' | 'created_at' | 'updated_at'>>,
): Promise<BuyButtonData> => {
  const { data } = await api.patch<BuyButtonData>(tenantPath(tenantSlug, `buttons/${id}`), payload, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  return data
}

export const deleteBuyButton = async (tenantSlug: string, idToken: string, id: string): Promise<void> => {
  await api.delete(tenantPath(tenantSlug, `buttons/${id}`), {
    headers: { Authorization: `Bearer ${idToken}` },
  })
}

export const listPricingTables = async (tenantSlug: string, idToken: string): Promise<PricingTableData[]> => {
  const { data } = await api.get<PricingTableData[]>(tenantPath(tenantSlug, 'pricing-tables'), {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  return data
}

export const createPricingTable = async (
  tenantSlug: string,
  idToken: string,
  payload: { name: string; template: string; show_toggle: boolean; tiers: PricingTierData[] },
): Promise<PricingTableData> => {
  const { data } = await api.post<PricingTableData>(tenantPath(tenantSlug, 'pricing-tables'), payload, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  return data
}

export const updatePricingTable = async (
  tenantSlug: string,
  idToken: string,
  id: string,
  payload: { name?: string; template?: string; show_toggle?: boolean; tiers?: PricingTierData[] },
): Promise<PricingTableData> => {
  const { data } = await api.patch<PricingTableData>(tenantPath(tenantSlug, `pricing-tables/${id}`), payload, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  return data
}

export const deletePricingTable = async (tenantSlug: string, idToken: string, id: string): Promise<void> => {
  await api.delete(tenantPath(tenantSlug, `pricing-tables/${id}`), {
    headers: { Authorization: `Bearer ${idToken}` },
  })
}

export const checkHeaderScript = async (
  tenantSlug: string,
  idToken: string,
): Promise<{ installed: boolean; url: string | null; error: string | null }> => {
  const { data } = await api.get<{ installed: boolean; url: string | null; error: string | null }>(
    tenantPath(tenantSlug, 'installation/check-script'),
    { headers: { Authorization: `Bearer ${idToken}` } },
  )
  return data
}

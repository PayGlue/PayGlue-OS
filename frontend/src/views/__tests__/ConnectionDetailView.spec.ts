// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

// PG-219, the first customer bug report: the webhook URL was handed out with a
// bare "&key=" and every provider rejected it. Two independent causes, both
// covered here, because the URL is worthless without the key and it looked
// perfectly copyable while being broken.

import { render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ConnectionDetailView from '../ConnectionDetailView.vue'
import { useSessionStore } from '../../stores/session'
import { apiBaseUrl } from '../../lib/publicUrls'

// Hoisted: vi.mock's factory runs before module-level code, so the shared spies
// and the error class have to be created here to be visible to both.
const h = vi.hoisted(() => {
  class ApiHttpError extends Error {
    status: number
    constructor(message: string, status: number) {
      super(message)
      this.status = status
    }
  }
  return {
    ApiHttpError,
    getIntegrationConfig: vi.fn(),
    getTenantWebhookSecret: vi.fn(),
  }
})

vi.mock('../../lib/api', () => ({
  ApiHttpError: h.ApiHttpError,
  getIntegrationConfig: h.getIntegrationConfig,
  getTenantWebhookSecret: h.getTenantWebhookSecret,
  getLemonSqueezyStores: vi.fn().mockResolvedValue({ stores: [] }),
  getPolarProducts: vi.fn().mockResolvedValue({ products: [], has_token: false }),
  runIntegrationHealthCheck: vi.fn(),
  setIntegrationCredentials: vi.fn(),
  updateIntegrationConfig: vi.fn(),
  postAuthSession: vi.fn(),
}))

const { ApiHttpError, getIntegrationConfig, getTenantWebhookSecret } = h

const renderView = async (provider: import('../../lib/connectionProviders').ProviderKey = 'polar') => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/t/:tenantSlug/connection/:provider', component: ConnectionDetailView, props: true },
      { path: '/login', component: { template: '<div />' } },
      { path: '/tenant/select', component: { template: '<div />' } },
    ],
  })
  router.push(`/t/tenant-a/connection/${provider}`)
  await router.isReady()

  render(ConnectionDetailView, {
    props: { provider },
    global: { plugins: [router] },
  })
}

// queryAll, not getAll: one assertion here is that no such field exists at all,
// and getAll throws instead of returning nothing.
// Matches on the path, not on a host: since PG-238 the origin depends on
// where the install runs, so anchoring on ours would only ever pass here.
const webhookInput = () =>
  screen.queryAllByDisplayValue(/\/webhooks\//).at(0) as HTMLInputElement | undefined

describe('ConnectionDetailView webhook URL', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    const session = useSessionStore()
    session.$patch({
      user: { id: 'test-uid', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [
        { tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner' },
      ],
    })
    session.activeTenantSlug = 'tenant-a'
    getTenantWebhookSecret.mockResolvedValue({ webhook_secret: 'whk_live_secret' })
  })

  it('still shows the key when the provider has never been configured', async () => {
    // The exact customer case. A brand-new provider has no IntegrationConfig
    // row, so the config request 404s. That used to abort the whole load and
    // skip the webhook-secret fetch with it, leaving "&key=" empty on every
    // first-time setup.
    getIntegrationConfig.mockRejectedValue(new ApiHttpError('Not found.', 404))

    await renderView()

    await waitFor(() => {
      expect(webhookInput()).toBeDefined()
    })
    expect(webhookInput()!.value).toContain('key=whk_live_secret')
    expect(webhookInput()!.value).not.toMatch(/key=$/)
  })

  it('offers a retry instead of a URL without a key when the secret fails to load', async () => {
    getIntegrationConfig.mockResolvedValue({
      provider_key: 'polar',
      provider_type: 'polar',
      enabled: false,
      metadata: {},
    })
    getTenantWebhookSecret.mockRejectedValue(new Error('network'))

    await renderView()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    })
    // Never hand out a URL that cannot work.
    expect(webhookInput()).toBeUndefined()
  })

  it('renders the key for a configured provider', async () => {
    getIntegrationConfig.mockResolvedValue({
      provider_key: 'polar',
      provider_type: 'polar',
      enabled: true,
      metadata: {},
    })

    await renderView()

    await waitFor(() => {
      expect(webhookInput()).toBeDefined()
    })
    expect(webhookInput()!.value).toBe(
      `${apiBaseUrl()}/webhooks/polar?tenant=tenant-a&key=whk_live_secret`,
    )
  })
})

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import IntegrationsView from '../IntegrationsView.vue'
import { useSessionStore } from '../../stores/session'
import {
  getIntegrationConfig,
  runIntegrationHealthCheck,
  setIntegrationCredentials,
  updateIntegrationConfig,
} from '../../lib/api'

vi.mock('../../lib/api', async () => {
  return {
    getIntegrationConfig: vi.fn(),
    updateIntegrationConfig: vi.fn(),
    setIntegrationCredentials: vi.fn(),
    runIntegrationHealthCheck: vi.fn(),
  }
})

const setupSession = (role: 'owner' | 'admin' | 'billing_admin' | 'support_readonly') => {
  setActivePinia(createPinia())
  const session = useSessionStore()
  session.$patch({
    user: { id: 'test-uid', email: 'user@example.com' } as any,
    memberships: [{ tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role }],
  })
  session.activeTenantSlug = 'tenant-a'
}

const makeRouter = async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/t/:tenantSlug/integrations', component: IntegrationsView },
      { path: '/login', component: { template: '<div />' } },
      { path: '/tenant/select', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/mappings', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/team', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/pricing', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/events', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/billing', component: { template: '<div />' } },
    ],
  })
  router.push('/t/tenant-a/integrations')
  await router.isReady()
  return router
}

describe('IntegrationsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getIntegrationConfig).mockImplementation(async (_tenantSlug, _token, providerKey) => {
      if (providerKey === 'payment') {
        return {
          provider_key: 'payment',
          enabled: true,
          provider_type: 'polar',
          metadata: { region: 'eu' },
        }
      }
      return {
        provider_key: 'cms',
        enabled: true,
        provider_type: 'ghost',
        metadata: { site_url: 'https://ghost.example.com' },
      }
    })
    vi.mocked(updateIntegrationConfig).mockResolvedValue({
      provider_key: 'payment',
      enabled: true,
      provider_type: 'polar',
      metadata: { region: 'us' },
    })
    vi.mocked(setIntegrationCredentials).mockResolvedValue({
      provider_key: 'payment',
      provider_type: 'polar',
      credential_ref: { backend: 'firestore', masked_keys: ['api_key'] },
    })
    vi.mocked(runIntegrationHealthCheck).mockResolvedValue({
      ok: true,
      code: 'ok',
      message: 'reachable',
      checked_at: '2026-01-01T00:00:00Z',
    })
  })

  it('loads payment and cms configs', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(IntegrationsView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(screen.getByText(/Payment integration/i)).toBeInTheDocument()
      expect(screen.getByDisplayValue('polar')).toBeInTheDocument()
      expect(screen.getByDisplayValue('ghost')).toBeInTheDocument()
    })
    expect(getIntegrationConfig).toHaveBeenCalledTimes(2)
  })

  it('allows owners to update credentials and run health checks', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(IntegrationsView, { global: { plugins: [router] } })

    await screen.findByText(/CMS integration/i)
    const paymentCredentialInput = screen.getByLabelText('payment credentials')
    await fireEvent.update(paymentCredentialInput, '{"api_key":"secret"}')

    await fireEvent.click(screen.getByRole('button', { name: /save payment credentials/i }))
    await fireEvent.click(screen.getByRole('button', { name: /run payment health check/i }))

    await waitFor(() => {
      expect(setIntegrationCredentials).toHaveBeenCalledWith('tenant-a', 'token', 'payment', {
        api_key: 'secret',
      })
      expect(runIntegrationHealthCheck).toHaveBeenCalledWith('tenant-a', 'token', 'payment')
      expect(screen.getByText(/reachable/i)).toBeInTheDocument()
    })
  })

  it('saves cms credentials from guided Ghost fields', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(IntegrationsView, { global: { plugins: [router] } })

    await screen.findByText(/CMS integration/i)
    await fireEvent.update(screen.getByLabelText('API URL'), 'https://ghost.example.com/ghost/api/admin')
    await fireEvent.update(screen.getByLabelText('Content API key'), 'content_api_abc')
    await fireEvent.update(screen.getByLabelText('Admin API key'), 'kid:abcdef123456')
    await fireEvent.update(screen.getByLabelText('Ghost health path'), '/site/')
    await fireEvent.update(screen.getByLabelText('Ghost entitlements path'), '/members/entitlements/')

    await fireEvent.click(screen.getByRole('button', { name: /save cms credentials/i }))

    await waitFor(() => {
      expect(setIntegrationCredentials).toHaveBeenCalledWith('tenant-a', 'token', 'cms', {
        api_base_url: 'https://ghost.example.com/ghost/api/admin',
        content_api_key: 'content_api_abc',
        admin_api_key: 'kid:abcdef123456',
        health_path: '/site/',
        entitlements_path: '/members/entitlements/',
      })
    })
  })

  it('keeps readonly roles in view-only mode', async () => {
    setupSession('support_readonly')
    const router = await makeRouter()

    render(IntegrationsView, { global: { plugins: [router] } })

    await screen.findByText(/Payment integration/i)
    const saveConfigButton = screen.getByRole('button', { name: /save payment config/i })
    const saveCredentialsButton = screen.getByRole('button', { name: /save payment credentials/i })
    const healthButton = screen.getByRole('button', { name: /run payment health check/i })

    expect(saveConfigButton).toBeDisabled()
    expect(saveCredentialsButton).toBeDisabled()
    expect(healthButton).toBeDisabled()

    await fireEvent.click(saveConfigButton)
    expect(updateIntegrationConfig).not.toHaveBeenCalled()
  })

  it('shows validation error when credentials contain non-string values', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(IntegrationsView, { global: { plugins: [router] } })

    await screen.findByText(/Payment integration/i)
    const paymentCredentialInput = screen.getByLabelText('payment credentials')
    await fireEvent.update(paymentCredentialInput, '{"api_key": true}')
    await fireEvent.click(screen.getByRole('button', { name: /save payment credentials/i }))

    await waitFor(() => {
      expect(screen.getByText(/must be a string value/i)).toBeInTheDocument()
    })
    expect(setIntegrationCredentials).not.toHaveBeenCalled()
  })

  it('shows validation error when Ghost API base URL is invalid', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(IntegrationsView, { global: { plugins: [router] } })

    await screen.findByText(/CMS integration/i)
    await fireEvent.update(screen.getByLabelText('API URL'), 'ghost-api')
    await fireEvent.update(screen.getByLabelText('Admin API key'), 'kid:abcdef123456')

    await fireEvent.click(screen.getByRole('button', { name: /save cms credentials/i }))

    await waitFor(() => {
      expect(screen.getByText(/API URL must be a valid URL/i)).toBeInTheDocument()
    })
    expect(setIntegrationCredentials).not.toHaveBeenCalled()
  })

  it('shows validation error when Ghost Admin API key format is invalid', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(IntegrationsView, { global: { plugins: [router] } })

    await screen.findByText(/CMS integration/i)
    await fireEvent.update(screen.getByLabelText('API URL'), 'https://ghost.example.com/ghost/api/admin')
    await fireEvent.update(screen.getByLabelText('Admin API key'), 'invalid-key')

    await fireEvent.click(screen.getByRole('button', { name: /save cms credentials/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/Admin API key must use the format <id>:<secret>/i),
      ).toBeInTheDocument()
    })
    expect(setIntegrationCredentials).not.toHaveBeenCalled()
  })
})

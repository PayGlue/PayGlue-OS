// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { render, screen, waitFor, fireEvent } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import PlansView from '../PlansView.vue'
import { useSessionStore } from '../../stores/session'
import { createCreemCheckoutSession, getTenantUsage } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  return {
    getTenantUsage: vi.fn(),
    createCreemCheckoutSession: vi.fn(),
  }
})

const setupSession = (role: 'owner' | 'admin' | 'billing_admin' | 'support_readonly') => {
  setActivePinia(createPinia())
  const session = useSessionStore()
  session.$patch({
    user: { id: 'test-uid', email: 'user@example.com' } as any,
    accessToken: 'fake-access-token',
    memberships: [{ tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role }],
  })
  session.activeTenantSlug = 'tenant-a'
}

const makeRouter = async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/t/:tenantSlug/plans', component: PlansView },
      { path: '/login', component: { template: '<div />' } },
      { path: '/tenant/select', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/mappings', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/team', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/pricing', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/integrations', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/events', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/billing', component: { template: '<div />' } },
    ],
  })
  router.push('/t/tenant-a/plans')
  await router.isReady()
  return router
}

describe('PlansView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getTenantUsage).mockResolvedValue({ plan: 'solo', usage: {} })
  })

  it('renders all three tiers and marks the current plan', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(PlansView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(screen.getAllByText('Current plan').length).toBeGreaterThan(0)
    })
    expect(screen.getByText('Solo')).toBeInTheDocument()
    expect(screen.getByText('Studio')).toBeInTheDocument()
    expect(screen.getByText('Agency')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /switch to studio/i })).toBeInTheDocument()
  })

  it('starts a Creem checkout session and redirects to it', async () => {
    setupSession('owner')
    const router = await makeRouter()
    vi.mocked(createCreemCheckoutSession).mockResolvedValue({
      checkout_url: 'https://creem.io/checkout/sess_abc',
    })

    const originalLocation = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, href: '', origin: 'https://app.payglue.io' },
    })

    render(PlansView, { global: { plugins: [router] } })

    await waitFor(() => screen.getByRole('button', { name: /switch to studio/i }))
    await fireEvent.click(screen.getByRole('button', { name: /switch to studio/i }))

    await waitFor(() => {
      expect(createCreemCheckoutSession).toHaveBeenCalledWith('tenant-a', 'fake-access-token', {
        planKey: 'studio',
        interval: 'monthly',
        returnUrl: 'https://app.payglue.io/t/tenant-a/billing',
      })
    })
    expect(window.location.href).toBe('https://creem.io/checkout/sess_abc')

    Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
  })

  it('switches an existing subscription in place without redirecting', async () => {
    setupSession('owner')
    const router = await makeRouter()
    vi.mocked(createCreemCheckoutSession).mockResolvedValue({
      updated: true,
      subscription: { id: 'sub_1', status: 'active' },
    })

    render(PlansView, { global: { plugins: [router] } })

    await waitFor(() => screen.getByRole('button', { name: /switch to studio/i }))
    await fireEvent.click(screen.getByRole('button', { name: /switch to studio/i }))

    await waitFor(() => {
      expect(screen.getByText(/switched to studio/i)).toBeInTheDocument()
    })
    expect(getTenantUsage).toHaveBeenCalledTimes(2)
  })

  it('shows read-only mode for non billing roles', async () => {
    setupSession('admin')
    const router = await makeRouter()

    render(PlansView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(screen.getAllByText(/your role can view plans but cannot make changes/i).length).toBeGreaterThan(0)
    })
    expect(screen.queryByRole('button', { name: /switch to studio/i })).not.toBeInTheDocument()
  })

  it('warns a Founding Member before they switch off their unlimited plan', async () => {
    setupSession('owner')
    const router = await makeRouter()
    vi.mocked(getTenantUsage).mockResolvedValue({ plan: 'founding', usage: {} })

    render(PlansView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(screen.getByText(/you're a founding member/i)).toBeInTheDocument()
    })
    expect(screen.queryByText('Current plan')).not.toBeInTheDocument()
  })
})

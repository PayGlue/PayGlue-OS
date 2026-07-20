// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import BillingView from '../BillingView.vue'
import { useSessionStore } from '../../stores/session'
import { getCreemSubscription, getCreemInvoices, cancelCreemSubscription } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  return {
    getCreemSubscription: vi.fn(),
    getCreemInvoices: vi.fn(),
    cancelCreemSubscription: vi.fn(),
    getTenantUsage: vi.fn().mockResolvedValue({ plan: 'solo', usage: {} }),
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
      { path: '/t/:tenantSlug/billing', component: BillingView },
      { path: '/login', component: { template: '<div />' } },
      { path: '/tenant/select', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/mappings', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/team', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/pricing', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/integrations', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/events', component: { template: '<div />' } },
    ],
  })
  router.push('/t/tenant-a/billing')
  await router.isReady()
  return router
}

const activeSubscription = {
  id: 'sub_1',
  status: 'active',
  amount: 2900,
  currency: 'eur',
  recurring_interval: 'month',
  cancel_at_period_end: false,
  current_period_end: '2026-08-01T00:00:00Z',
  product: { name: 'Solo Plan' },
}

const invoice = {
  id: 'inv_1',
  created_at: '2026-07-01T00:00:00Z',
  amount: 2900,
  currency: 'eur',
  product: { name: 'Solo Plan' },
}

describe('BillingView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getCreemSubscription).mockResolvedValue({
      subscriptions: [activeSubscription],
      portal_link: 'https://creem.io/portal/abc',
    })
    vi.mocked(getCreemInvoices).mockResolvedValue({
      invoices: [invoice],
      portal_link: 'https://creem.io/portal/abc',
    })
  })

  it('renders active subscription and invoice history from the Creem API', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(BillingView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(screen.getAllByText('Solo Plan').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText(/29[.,]00/).length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /manage on creem/i })).toHaveAttribute(
      'href',
      'https://creem.io/portal/abc',
    )
  })

  it('shows read-only mode for non billing roles', async () => {
    setupSession('admin')
    const router = await makeRouter()

    render(BillingView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(getCreemSubscription).toHaveBeenCalledWith('tenant-a', 'fake-access-token')
    })
    expect(screen.getByText(/your role can view billing but cannot make changes/i)).toBeInTheDocument()
    expect(screen.queryByText(/danger zone/i)).not.toBeInTheDocument()
  })

  it('cancels the subscription after the two-step confirmation', async () => {
    setupSession('owner')
    const router = await makeRouter()
    vi.mocked(cancelCreemSubscription).mockResolvedValue({
      status: 'canceled',
      current_period_end_date: '2026-08-01T00:00:00Z',
    })

    render(BillingView, { global: { plugins: [router] } })

    await waitFor(() => screen.getByText(/danger zone/i))
    expect(screen.queryByRole('button', { name: /^cancel subscription$/i })).not.toBeInTheDocument()

    await fireEvent.click(screen.getByRole('button', { name: /i have read and understand these effects/i }))
    await fireEvent.click(screen.getByRole('button', { name: /^cancel subscription$/i }))

    await waitFor(() => {
      expect(cancelCreemSubscription).toHaveBeenCalledWith('tenant-a', 'fake-access-token')
    })
    await waitFor(() => {
      expect(screen.getByText(/subscription canceled/i)).toBeInTheDocument()
    })
  })
})

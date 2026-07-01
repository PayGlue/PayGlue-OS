// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import BillingView from '../BillingView.vue'
import { useSessionStore } from '../../stores/session'
import { getPolarSubscriptions, getPolarInvoices, cancelPolarSubscription } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  return {
    getPolarSubscriptions: vi.fn(),
    getPolarInvoices: vi.fn(),
    cancelPolarSubscription: vi.fn(),
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
  product: { name: 'Pro Plan' },
}

const invoice = {
  id: 'inv_1',
  created_at: '2026-07-01T00:00:00Z',
  amount: 2900,
  currency: 'eur',
  status: 'paid',
  product: { name: 'Pro Plan' },
}

describe('BillingView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getPolarSubscriptions).mockResolvedValue({ subscriptions: [activeSubscription] })
    vi.mocked(getPolarInvoices).mockResolvedValue({ invoices: [invoice] })
    vi.mocked(cancelPolarSubscription).mockResolvedValue({})
  })

  it('renders active subscription and invoice history from API', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(BillingView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(screen.getAllByText('Pro Plan').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText(/29[.,]00/).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /cancel plan/i })).toBeInTheDocument()
  })

  it('allows owner/billing_admin roles to cancel the subscription', async () => {
    setupSession('billing_admin')
    const router = await makeRouter()

    render(BillingView, { global: { plugins: [router] } })

    await screen.findByRole('button', { name: /cancel plan/i })
    await fireEvent.click(screen.getByRole('button', { name: /cancel plan/i }))
    await fireEvent.click(screen.getByRole('button', { name: /yes, cancel/i }))

    await waitFor(() => {
      expect(cancelPolarSubscription).toHaveBeenCalledWith(
        'tenant-a',
        'fake-access-token',
        'sub_1',
        false,
      )
    })
  })

  it('shows read-only mode for non billing roles', async () => {
    setupSession('admin')
    const router = await makeRouter()

    render(BillingView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(getPolarSubscriptions).toHaveBeenCalledWith('tenant-a', 'fake-access-token')
    })
    expect(screen.getByText(/your role can view billing but cannot make changes/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /cancel plan/i })).not.toBeInTheDocument()
  })
})

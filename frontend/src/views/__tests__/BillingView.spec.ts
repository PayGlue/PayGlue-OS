// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import BillingView from '../BillingView.vue'
import { useSessionStore } from '../../stores/session'
import { getBillingProfile, updateBillingProfile } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  return {
    getBillingProfile: vi.fn(),
    updateBillingProfile: vi.fn(),
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

describe('BillingView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getBillingProfile).mockResolvedValue({
      legal_name: 'Acme GmbH',
      billing_email: 'finance@example.com',
      country_code: 'DE',
      tax_id: 'DE123456789',
    })
    vi.mocked(updateBillingProfile).mockResolvedValue({
      legal_name: 'Acme GmbH',
      billing_email: 'new-finance@example.com',
      country_code: 'DE',
      tax_id: 'DE123456789',
    })
  })

  it('renders billing profile from API', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(BillingView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(screen.getByDisplayValue('Acme GmbH')).toBeInTheDocument()
      expect(screen.getByDisplayValue('finance@example.com')).toBeInTheDocument()
    })
  })

  it('allows owner/billing_admin roles to update billing', async () => {
    setupSession('billing_admin')
    const router = await makeRouter()

    render(BillingView, { global: { plugins: [router] } })

    await screen.findByDisplayValue('finance@example.com')
    await fireEvent.update(screen.getByLabelText('billing email'), 'new-finance@example.com')
    await fireEvent.click(screen.getByRole('button', { name: /save billing profile/i }))

    await waitFor(() => {
      expect(updateBillingProfile).toHaveBeenCalledWith('tenant-a', 'token', {
        legal_name: 'Acme GmbH',
        billing_email: 'new-finance@example.com',
        country_code: 'DE',
        tax_id: 'DE123456789',
      })
    })
  })

  it('shows read-only mode for non billing roles', async () => {
    setupSession('admin')
    const router = await makeRouter()

    render(BillingView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(getBillingProfile).toHaveBeenCalledWith('tenant-a', 'token')
    })
    await waitFor(() => {
      expect(screen.queryByText(/loading billing profile/i)).not.toBeInTheDocument()
    })
    const saveButton = screen.getByRole('button', { name: /save billing profile/i })
    expect(saveButton).toBeDisabled()

    await fireEvent.click(saveButton)
    expect(updateBillingProfile).not.toHaveBeenCalled()
  })
})

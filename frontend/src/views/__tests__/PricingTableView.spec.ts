// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { render, screen } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { setActivePinia, createPinia } from 'pinia'
import PricingTableView from '../PricingTableView.vue'
import { useSessionStore } from '../../stores/session'

describe('PricingTableView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const session = useSessionStore()
    session.$patch({
      user: { id: 'test-uid', email: 'owner@example.com' } as any,
      memberships: [{ tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner' }],
    })
    session.activeTenantSlug = 'tenant-a'
  })

  it('renders embed snippet and plan preview blocks', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/t/:tenantSlug/pricing', component: PricingTableView },
        { path: '/login', component: { template: '<div />' } },
        { path: '/tenant/select', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/mappings', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/team', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/integrations', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/events', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/billing', component: { template: '<div />' } },
      ],
    })
    router.push('/t/tenant-a/pricing')
    await router.isReady()

    render(PricingTableView, {
      global: {
        plugins: [router],
      },
    })

    expect(screen.getByText(/Ghost pricing table module/i)).toBeInTheDocument()
    expect(screen.getByText(/Embed snippet for Ghost/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start Starter/i })).toBeInTheDocument()
    expect(screen.getByText(/pricing-table.js/i)).toBeInTheDocument()
  })
})

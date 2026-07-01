// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import MappingsView from '../MappingsView.vue'
import { useSessionStore } from '../../stores/session'

vi.mock('../../lib/api', async () => {
  return {
    ApiHttpError: class ApiHttpError extends Error {
      status: number
      constructor(message: string, status: number) {
        super(message)
        this.status = status
      }
    },
    listMappings: vi.fn().mockResolvedValue([
      {
        id: 1,
        payment_provider: 'polar',
        event_type: 'order.paid',
        external_product_id: 'prod_basic',
        entitlement_key: 'tier.basic',
        action: 'grant',
        quantity: 1,
        is_active: true,
      },
    ]),
    createMapping: vi.fn(),
    deleteMapping: vi.fn(),
  }
})

describe('MappingsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const session = useSessionStore()
    session.$patch({
      user: { id: 'test-uid', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [{ tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner' }],
    })
    session.activeTenantSlug = 'tenant-a'
  })

  it('renders mappings loaded from API', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/t/:tenantSlug/mappings', component: MappingsView },
        { path: '/login', component: { template: '<div />' } },
        { path: '/tenant/select', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/team', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/pricing', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/integrations', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/events', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/billing', component: { template: '<div />' } },
      ],
    })
    router.push('/t/tenant-a/mappings')
    await router.isReady()

    render(MappingsView, {
      global: {
        plugins: [router],
      },
    })

    await waitFor(() => {
      expect(screen.getByText('prod_basic')).toBeInTheDocument()
    })
    expect(screen.getByText('polar')).toBeInTheDocument()
    expect(screen.getByText('One-time')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })
})

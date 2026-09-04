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
        metadata: { ghost_subscribed: true, ghost_email_types: ['signin'] },
        used_in: ['Buy Button: Go Pro', 'Pricing Table: Homepage · Pro'],
      },
      {
        id: 2,
        payment_provider: 'polar',
        event_type: 'subscription.canceled',
        external_product_id: 'prod_basic',
        entitlement_key: 'tier.basic',
        action: 'revoke',
        quantity: 1,
        is_active: true,
        metadata: {},
        used_in: ['Buy Button: Go Pro', 'Pricing Table: Homepage · Pro'],
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

  it('says what buying the product does, rather than printing table columns', async () => {
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

    // The sentence, not the fields it is built from. `product:tier-basic` is
    // the label the Ghost adapter really writes, so the page names it.
    expect(
      screen.getByText(
        'Buying this grants access in Ghost and labels the member product:tier-basic, and subscribes them to your newsletter. They receive a magic-link email.',
      ),
    ).toBeInTheDocument()

    // The grant and the revoke are two rules for one product and share a line.
    expect(screen.getByText('A cancellation takes that access away again.')).toBeInTheDocument()
    expect(screen.getAllByText('Send test')).toHaveLength(1)

    expect(screen.getByText('Offered in Buy Button: Go Pro · Pricing Table: Homepage · Pro')).toBeInTheDocument()

    // "Active" used to sit on every row, which makes it decoration rather than
    // a signal. Only a paused rule says anything now.
    expect(screen.queryByText('Active')).toBeNull()
    expect(screen.queryByText('Paused')).toBeNull()
  })
})

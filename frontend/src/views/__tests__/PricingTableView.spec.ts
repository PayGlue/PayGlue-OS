// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { setActivePinia, createPinia } from 'pinia'
import PricingTableView from '../PricingTableView.vue'
import { useSessionStore } from '../../stores/session'
import { createPricingTable, listMappings, listPricingTables } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  return {
    listPricingTables: vi.fn().mockResolvedValue([]),
    createPricingTable: vi.fn(),
    updatePricingTable: vi.fn(),
    deletePricingTable: vi.fn(),
    getPolarProducts: vi.fn().mockResolvedValue([]),
    getLemonSqueezyProducts: vi.fn().mockResolvedValue([]),
    getPayPalProducts: vi.fn().mockResolvedValue([]),
    listMappings: vi.fn().mockResolvedValue([]),
    createMapping: vi.fn(),
    updateMapping: vi.fn(),
  }
})

describe('PricingTableView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    const session = useSessionStore()
    session.$patch({
      user: { id: 'test-uid', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [{ tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner' }],
    })
    session.activeTenantSlug = 'tenant-a'
    vi.mocked(listPricingTables).mockResolvedValue([])
    vi.mocked(listMappings).mockResolvedValue([])
    vi.mocked(createPricingTable).mockResolvedValue({
      id: 'pt_1',
      name: 'Main pricing page',
      template: 'classic',
      show_toggle: false,
      accent_color: '#4f46e5',
      currency: 'EUR',
      tiers: [],
    } as any)
  })

  it('creates a pricing table and shows the embed snippet', async () => {
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

    await waitFor(() => {
      expect(screen.getByText(/no pricing tables yet/i)).toBeInTheDocument()
    })

    await fireEvent.click(screen.getByRole('button', { name: /new table/i }))
    await fireEvent.update(screen.getByPlaceholderText('Free'), 'Starter')
    await fireEvent.click(screen.getByRole('button', { name: /create table/i }))

    await waitFor(() => {
      expect(createPricingTable).toHaveBeenCalledWith(
        'tenant-a',
        'fake-access-token',
        expect.objectContaining({
          tiers: expect.arrayContaining([expect.objectContaining({ name: 'Starter' })]),
        }),
      )
    })

    await waitFor(() => {
      expect(screen.getByText(/table saved/i)).toBeInTheDocument()
    })
    expect(screen.getAllByText(/pricing-table\.js/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/data-table-id="pt_1"/i).length).toBeGreaterThan(0)
  })
})

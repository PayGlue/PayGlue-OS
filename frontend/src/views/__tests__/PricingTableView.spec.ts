// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { setActivePinia, createPinia } from 'pinia'
import PricingTableView from '../PricingTableView.vue'
import { useSessionStore } from '../../stores/session'
import { usePageResetStore } from '../../stores/pageReset'
import { createPricingTable, getPolarProducts, listMappings, listPricingTables } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  return {
    listPricingTables: vi.fn().mockResolvedValue([]),
    createPricingTable: vi.fn(),
    updatePricingTable: vi.fn(),
    deletePricingTable: vi.fn(),
    getPolarProducts: vi.fn().mockResolvedValue([]),
    getLemonSqueezyProducts: vi.fn().mockResolvedValue([]),
    getPayPalProducts: vi.fn().mockResolvedValue([]),
    getGumroadProducts: vi.fn().mockResolvedValue([]),
    getPaddleProducts: vi.fn().mockResolvedValue([]),
    getKofiProducts: vi.fn().mockResolvedValue([]),
    getCreemProducts: vi.fn().mockResolvedValue([]),
    getPatreonProducts: vi.fn().mockResolvedValue([]),
    getIntegrationConfig: vi.fn().mockResolvedValue({ enabled: false, metadata: {} }),
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

// PG-320 / PG-321: the toggle is a real switch, a tier without the toggle has
// one price with a period, and the feature icons include a cross.
describe('PricingTableView toggle switch and icons', () => {
  async function openEditor() {
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
    render(PricingTableView, { global: { plugins: [router] } })
    await waitFor(() => expect(screen.getByText(/no pricing tables yet/i)).toBeInTheDocument())
    await fireEvent.click(screen.getByRole('button', { name: /new table/i }))
  }

  beforeEach(() => {
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
      id: 'pt_2', name: 'x', template: 'classic', show_toggle: false, accent_color: '#4f46e5', currency: 'EUR', tiers: [],
    } as any)
  })

  async function chooseTierType(name: RegExp, index = 0) {
    await fireEvent.click(screen.getAllByRole('radio', { name })[index])
  }

  it('a new table starts with a free tier, and added tiers start as subscriptions', async () => {
    await openEditor()
    expect(screen.getAllByRole('radio', { name: /^free sign-up$/i })[0]).toHaveAttribute('aria-checked', 'true')
    await fireEvent.click(screen.getByRole('button', { name: /add tier/i }))
    expect(screen.getAllByRole('radio', { name: /^subscription$/i })[1]).toHaveAttribute('aria-checked', 'true')
  })

  it('asks how you sell only once a tier is a subscription', async () => {
    await openEditor()
    expect(screen.queryByRole('radio', { name: /one price per tier/i })).not.toBeInTheDocument()
    await chooseTierType(/^subscription$/i)
    expect(screen.getByRole('radio', { name: /one price per tier/i })).toBeChecked()
    expect(screen.getByRole('radio', { name: /monthly \/ yearly toggle/i })).not.toBeChecked()
  })

  it('one price per tier saves show_toggle false and a yearly-only price', async () => {
    await openEditor()
    await chooseTierType(/^subscription$/i)
    expect(screen.queryByText('Yearly price')).not.toBeInTheDocument()

    await fireEvent.update(screen.getByLabelText('Price'), '60')
    await fireEvent.update(screen.getByLabelText('Billing period'), 'yr')
    await fireEvent.update(screen.getByPlaceholderText('Free'), 'Yearly')
    await fireEvent.click(screen.getByRole('button', { name: /create table/i }))

    await waitFor(() => expect(createPricingTable).toHaveBeenCalled())
    const payload = vi.mocked(createPricingTable).mock.calls[0][2] as any
    expect(payload.show_toggle).toBe(false)
    expect(payload.tiers[0].price_monthly).toBe('')
    expect(payload.tiers[0].price_yearly).toBe('60')
    expect(payload.tiers[0].product_id_yearly).toBe('')
  })

  it('the toggle mode asks for a yearly product and saves it with its checkout URL', async () => {
    vi.mocked(getPolarProducts).mockResolvedValue({
      has_token: true,
      sandbox: false,
      products: [
        { id: 'prod_m', name: 'Premium monthly', checkout_url: 'https://buy.example/m' },
        { id: 'prod_y', name: 'Premium yearly', checkout_url: 'https://buy.example/y' },
      ],
    } as any)
    await openEditor()
    await chooseTierType(/^subscription$/i)
    await fireEvent.click(screen.getByRole('radio', { name: /monthly \/ yearly toggle/i }))
    expect(screen.getByText('Yearly price')).toBeInTheDocument()

    await waitFor(() => expect(screen.getByLabelText('Yearly product')).toBeInTheDocument())
    const selects = screen.getAllByRole('combobox').filter(el =>
      Array.from((el as HTMLSelectElement).options).some(o => o.value === 'prod_m'),
    ) as HTMLSelectElement[]
    expect(selects.length).toBe(2)
    await fireEvent.update(selects[0], 'prod_m')
    await fireEvent.update(screen.getByLabelText('Yearly product'), 'prod_y')
    expect((screen.getByLabelText('Yearly checkout URL') as HTMLInputElement).value).toBe('https://buy.example/y')

    await fireEvent.update(screen.getByPlaceholderText('Free'), 'Premium')
    await fireEvent.click(screen.getByRole('button', { name: /create table/i }))
    await waitFor(() => expect(createPricingTable).toHaveBeenCalled())
    const payload = vi.mocked(createPricingTable).mock.calls[0][2] as any
    expect(payload.show_toggle).toBe(true)
    expect(payload.tiers[0].product_id).toBe('prod_m')
    expect(payload.tiers[0].product_id_yearly).toBe('prod_y')
    expect(payload.tiers[0].cta_url_yearly).toBe('https://buy.example/y')
    expect(payload.tiers[0].grant.entitlement_key).toBe('product-prod_m')
  })

  it('switching on the toggle turns one-time tiers into subscriptions and leaves free tiers alone', async () => {
    await openEditor()
    await chooseTierType(/^one-time$/i, 0)
    await fireEvent.click(screen.getByRole('button', { name: /add tier/i }))
    await chooseTierType(/^free sign-up$/i, 1)
    await fireEvent.click(screen.getByRole('button', { name: /add tier/i }))
    await chooseTierType(/^subscription$/i, 2)

    await fireEvent.click(screen.getByRole('radio', { name: /monthly \/ yearly toggle/i }))

    const subscriptionRadios = screen.getAllByRole('radio', { name: /^subscription$/i })
    expect(subscriptionRadios[0]).toHaveAttribute('aria-checked', 'true')
    expect(screen.getAllByRole('radio', { name: /^free sign-up$/i })[1]).toHaveAttribute('aria-checked', 'true')
    expect(subscriptionRadios[2]).toHaveAttribute('aria-checked', 'true')
  })

  it('renders a live preview built from the form', async () => {
    await openEditor()
    await fireEvent.update(screen.getByPlaceholderText('Free'), 'Supporter')
    await waitFor(() => {
      const doc = screen.getByTitle('Pricing table preview').getAttribute('srcdoc') ?? ''
      expect(doc).toContain('"name":"Supporter"')
      expect(doc).toContain('/pricing-table.js" data-table-id="preview"')
    }, { timeout: 2000 })
  })

  it('clicking the page you are on again closes the editor', async () => {
    await openEditor()
    expect(screen.getByText(/new pricing table/i)).toBeInTheDocument()
    usePageResetStore().reset()
    await waitFor(() => expect(screen.queryByText(/new pricing table/i)).not.toBeInTheDocument())
  })

  it('offers a cross among the feature icons', async () => {
    await openEditor()
    await fireEvent.click(screen.getByRole('button', { name: /^add$/i }))
    expect(screen.getAllByTitle('cross').length).toBeGreaterThan(0)
  })
})

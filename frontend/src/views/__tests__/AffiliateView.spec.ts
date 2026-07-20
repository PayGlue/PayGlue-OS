// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// The page sits behind the login, so it cannot be clicked through without a
// real session. These tests are the substitute: they prove it renders at all,
// and pin the two things a redesign could quietly break -- where the button
// goes, and whether the Creem caveat is still on the page.

import { render, screen } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import AffiliateView from '../AffiliateView.vue'
import { useSessionStore } from '../../stores/session'

const JOIN_URL = 'https://affiliates.creem.io/join/payglue'

const mountView = async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/login', component: { template: '<div />' } },
      { path: '/tenant/select', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/affiliate', component: AffiliateView },
    ],
  })
  router.push('/t/tenant-a/affiliate')
  await router.isReady()
  render(AffiliateView, { global: { plugins: [router] } })
}

describe('AffiliateView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const session = useSessionStore()
    session.$patch({
      user: { id: 'test-uid', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [
        { tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner' },
      ],
    })
    session.activeTenantSlug = 'tenant-a'
  })

  it('renders the offer rather than a list of facts', async () => {
    await mountView()
    expect(screen.getByText(/Get paid for/)).toBeTruthy()
    expect(screen.getByText(/word of mouth/)).toBeTruthy()
  })

  it('sends both calls to action to the Creem programme', async () => {
    await mountView()
    const links = screen
      .getAllByRole('link')
      .filter((a) => a.getAttribute('href') === JOIN_URL)

    // Hero and the closing section. A redesign that drops one loses half the
    // conversions without anything failing.
    expect(links.length).toBe(2)
    for (const link of links) {
      expect(link.getAttribute('target')).toBe('_blank')
      expect(link.getAttribute('rel')).toBe('noopener')
    }
  })

  it('keeps the separate-Creem-account caveat visible', async () => {
    await mountView()
    expect(screen.getByText(/creating a Creem account/)).toBeTruthy()
  })

  it('shows the three headline numbers', async () => {
    await mountView()
    expect(screen.getByText(/of every payment/)).toBeTruthy()
    expect(screen.getByText(/cookie window/)).toBeTruthy()
    expect(screen.getByText(/no minimum payout/)).toBeTruthy()
  })

  it('computes the commission from the real plan price', async () => {
    // The previous version carried three hand-written figures that were about a
    // quarter of the truth. These come from the live ladder and PLAN_TIERS, so
    // they cannot drift from the pricing page without this failing.
    await mountView()

    // Default state: Founding, 5 referrals -> 40% of 9 x 5 x 12. Founding is
    // preselected because it is the only plan anybody can buy today; the
    // 9 € here is useFoundingTier's pre-hydration default, since the Supabase
    // fetch never resolves in jsdom.
    const expected = 9 * 0.4 * 5 * 12
    expect(screen.getByText(new RegExp(`${expected}\\s*€`))).toBeTruthy()
  })

  it('lets the reader pick the plan the referral is on', async () => {
    await mountView()
    for (const name of ['Founding', 'Solo', 'Studio', 'Agency']) {
      expect(screen.getByRole('button', { name: new RegExp(name) })).toBeTruthy()
    }
  })

  it('explains where the number comes from', async () => {
    // The whole reason this replaced the old figures: an unexplained amount
    // reads as invented, and this one was.
    await mountView()
    expect(screen.getByText(/40% of the/)).toBeTruthy()
  })
})

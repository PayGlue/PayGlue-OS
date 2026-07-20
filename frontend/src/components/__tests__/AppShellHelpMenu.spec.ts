// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// The help menu lives behind the login, so it cannot be clicked through in a
// browser without a real session. These tests are the substitute: they pin the
// three destinations, because a menu item pointing at the wrong place looks
// exactly like one pointing at the right place until somebody clicks it.

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import AppShell from '../AppShell.vue'
import { useSessionStore } from '../../stores/session'

const mountShell = async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/login', component: { template: '<div />' } },
      { path: '/tenant/select', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/support', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/dashboard', component: { template: '<div />' } },
    ],
  })
  router.push('/t/tenant-a/dashboard')
  await router.isReady()
  render(AppShell, { global: { plugins: [router] } })
}

describe('AppShell help menu', () => {
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

  it('stays closed until the help button is used', async () => {
    await mountShell()
    expect(screen.queryByText('System Status')).toBeNull()
  })

  it('opens with all three destinations, each pointing where it claims', async () => {
    await mountShell()
    const buttons = screen.getAllByRole('button', { name: 'Help' })
    await fireEvent.click(buttons[0])

    await waitFor(() => expect(screen.getAllByText('Support').length).toBeGreaterThan(0))

    // Support is tenant-scoped: it is the page carrying the service pin, which
    // is why a generic support.payglue.io link would be the wrong target.
    const support = screen.getAllByRole('link', { name: /Support/ })[0]
    expect(support.getAttribute('href')).toContain('/t/tenant-a/support')

    const status = screen.getAllByRole('link', { name: /System Status/ })[0]
    expect(status.getAttribute('href')).toBe('https://status.payglue.io')

    const docs = screen.getAllByRole('link', { name: /Documentation/ })[0]
    expect(docs.getAttribute('href')).toBe('https://docs.payglue.io')
  })

  it('opens external links in a new tab without leaking the referrer', async () => {
    await mountShell()
    await fireEvent.click(screen.getAllByRole('button', { name: 'Help' })[0])
    await waitFor(() => expect(screen.getAllByText('System Status').length).toBeGreaterThan(0))

    for (const name of [/System Status/, /Documentation/]) {
      const link = screen.getAllByRole('link', { name })[0]
      expect(link.getAttribute('target')).toBe('_blank')
      expect(link.getAttribute('rel')).toBe('noopener')
    }
  })
})

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import TeamView from '../TeamView.vue'
import { useSessionStore } from '../../stores/session'

vi.mock('../../lib/api', async () => {
  return {
    listTeamMembers: vi.fn().mockResolvedValue([
      {
        id: 1,
        email: 'owner@example.com',
        firebase_uid: 'uid_owner',
        role: 'owner',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ]),
    addTeamMember: vi.fn(),
    updateTeamMemberRole: vi.fn(),
    removeTeamMember: vi.fn(),
  }
})

describe('TeamView', () => {
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

  it('renders loaded tenant members', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/t/:tenantSlug/team', component: TeamView },
        { path: '/login', component: { template: '<div />' } },
        { path: '/tenant/select', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/mappings', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/pricing', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/integrations', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/events', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/billing', component: { template: '<div />' } },
      ],
    })
    router.push('/t/tenant-a/team')
    await router.isReady()

    render(TeamView, {
      global: {
        plugins: [router],
      },
    })

    await waitFor(() => {
      expect(screen.getByText(/owner@example.com/i)).toBeInTheDocument()
    })
  })

  it('shows inline validation when no email is provided', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/t/:tenantSlug/team', component: TeamView },
        { path: '/login', component: { template: '<div />' } },
        { path: '/tenant/select', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/mappings', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/pricing', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/integrations', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/events', component: { template: '<div />' } },
        { path: '/t/:tenantSlug/billing', component: { template: '<div />' } },
      ],
    })
    router.push('/t/tenant-a/team')
    await router.isReady()

    const { container } = render(TeamView, {
      global: {
        plugins: [router],
      },
    })

    const submitButton = screen.getByRole('button', { name: /add member/i })
    submitButton.click()

    await waitFor(() => {
      expect(container.textContent).toContain('Enter the email address of the person you want to add.')
    })
  })
})

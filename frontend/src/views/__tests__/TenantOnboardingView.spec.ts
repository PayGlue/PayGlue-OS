// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TenantOnboardingView from '../TenantOnboardingView.vue'
import { useSessionStore } from '../../stores/session'

vi.mock('../../lib/api', () => ({
  createTenant: vi.fn(),
}))

import { createTenant } from '../../lib/api'

const buildRouter = () =>
  createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/tenant/create', name: 'tenant-onboarding', component: TenantOnboardingView },
      { path: '/t/:tenantSlug/mappings', name: 'mappings', component: { template: '<div>Mappings</div>' } },
      { path: '/tenant/select', name: 'tenant-select', component: { template: '<div>Select</div>' } },
    ],
  })

describe('TenantOnboardingView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    const session = useSessionStore()
    session.$patch({ user: { id: 'test-uid', email: 'owner@example.com' } as any, memberships: [] })
    session.activeTenantSlug = null
  })

  it('creates a tenant and opens it', async () => {
    vi.mocked(createTenant).mockResolvedValue({ tenant_slug: 'acme' })
    const session = useSessionStore()
    const bootstrapMock = vi.fn(async () => {
      session.memberships = [{ tenant_id: 'tid-1', tenant_slug: 'acme', tenant_name: 'Acme', role: 'owner' }]
      return true
    })
    session.bootstrap = bootstrapMock

    const router = buildRouter()
    router.push('/tenant/create')
    await router.isReady()

    render(TenantOnboardingView, {
      global: {
        plugins: [router],
      },
    })

    await fireEvent.update(screen.getByLabelText(/tenant slug/i), 'Acme Corp')
    await fireEvent.click(screen.getByRole('button', { name: /create tenant/i }))

    await waitFor(() => {
      expect(createTenant).toHaveBeenCalledWith('token', { slug: 'acme-corp' })
      expect(bootstrapMock).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(router.currentRoute.value.fullPath).toBe('/t/acme/mappings')
    })
  })

  it('shows API errors inline when tenant creation fails', async () => {
    vi.mocked(createTenant).mockRejectedValue(new Error('Tenant slug already exists'))

    const router = buildRouter()
    router.push('/tenant/create')
    await router.isReady()

    render(TenantOnboardingView, {
      global: {
        plugins: [router],
      },
    })

    await fireEvent.update(screen.getByLabelText(/tenant slug/i), 'Acme Corp')
    await fireEvent.click(screen.getByRole('button', { name: /create tenant/i }))

    await waitFor(() => {
      expect(screen.getByText(/tenant slug already exists/i)).toBeInTheDocument()
    })
  })
})

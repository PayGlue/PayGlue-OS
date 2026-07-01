// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TenantOnboardingView from '../TenantOnboardingView.vue'
import { useSessionStore } from '../../stores/session'

vi.mock('../../lib/api', () => ({
  api: { get: vi.fn() },
  createTenant: vi.fn(),
}))

vi.mock('../../lib/supabase', () => {
  const insertTenant = vi.fn().mockResolvedValue({ error: null })
  const insertMember = vi.fn().mockResolvedValue({ error: null })
  const single = vi.fn().mockResolvedValue({ data: { id: 'tenant-db-id' } })
  const eq = vi.fn(() => ({ single }))
  const select = vi.fn(() => ({ eq }))
  const from = vi.fn((table: string) => {
    if (table === 'tenant_members') return { insert: insertMember }
    return { insert: insertTenant, select }
  })
  return {
    supabase: {
      auth: {
        getUser: vi.fn().mockResolvedValue({ data: { user: { id: 'uid-1' } } }),
        getSession: vi.fn().mockResolvedValue({ data: { session: { access_token: 'sb-token' } } }),
      },
      from,
    },
    __mocks: { insertTenant, insertMember, single, eq, select, from },
  }
})

import { api, createTenant } from '../../lib/api'
// @ts-expect-error test-only export
import { supabase, __mocks } from '../../lib/supabase'

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
    vi.mocked(api.get).mockResolvedValue({ data: { available: true } } as any)
    __mocks.insertTenant.mockResolvedValue({ error: null })
    __mocks.insertMember.mockResolvedValue({ error: null })
    vi.mocked(supabase.auth.getUser).mockResolvedValue({ data: { user: { id: 'uid-1' } } } as any)
    vi.mocked(supabase.auth.getSession).mockResolvedValue({
      data: { session: { access_token: 'sb-token' } },
    } as any)

    const session = useSessionStore()
    session.$patch({
      user: { id: 'test-uid', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [],
    })
    session.activeTenantSlug = null
  })

  it('creates an organization and moves to the Ghost connection step', async () => {
    vi.mocked(createTenant).mockResolvedValue({ tenant_slug: 'acme-corp' } as any)
    const session = useSessionStore()
    const bootstrapMock = vi.fn(async () => {
      session.memberships = [{ tenant_id: 'tid-1', tenant_slug: 'acme-corp', tenant_name: 'Acme Corp', role: 'owner' }]
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

    await fireEvent.update(screen.getByPlaceholderText('Acme Media'), 'Acme Corp')

    await waitFor(() => {
      expect(screen.getByText('Available')).toBeInTheDocument()
    })

    await fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() => {
      expect(__mocks.insertTenant).toHaveBeenCalledWith(
        expect.objectContaining({ slug: 'acme-corp', name: 'Acme Corp', owner_id: 'uid-1' }),
      )
      expect(createTenant).toHaveBeenCalledWith('sb-token', { slug: 'acme-corp' })
      expect(bootstrapMock).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(session.activeTenantSlug).toBe('acme-corp')
      expect(screen.getByText(/connect your ghost blog/i)).toBeInTheDocument()
    })
  })

  it('shows API errors inline when tenant creation fails', async () => {
    __mocks.insertTenant.mockResolvedValue({ error: { message: 'Tenant slug already exists' } })

    const router = buildRouter()
    router.push('/tenant/create')
    await router.isReady()

    render(TenantOnboardingView, {
      global: {
        plugins: [router],
      },
    })

    await fireEvent.update(screen.getByPlaceholderText('Acme Media'), 'Acme Corp')

    await waitFor(() => {
      expect(screen.getByText('Available')).toBeInTheDocument()
    })

    await fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() => {
      expect(screen.getByText(/tenant slug already exists/i)).toBeInTheDocument()
    })
    expect(createTenant).not.toHaveBeenCalled()
  })
})

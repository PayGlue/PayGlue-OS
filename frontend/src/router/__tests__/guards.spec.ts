// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import router from '../index'
import { useSessionStore } from '../../stores/session'

describe('router guards', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    const session = useSessionStore()
    session.clearSession()
    await router.push('/login')
  })

  it('redirects unauthenticated users to login with redirect query', async () => {
    await router.push('/t/tenant-a/mappings')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/t/tenant-a/mappings')
  })

  it('redirects authenticated users with no memberships to onboarding', async () => {
    const session = useSessionStore()
    session.$patch({ user: { id: 'uid-1', email: 'owner@example.com' } as any, memberships: [] })

    await router.push('/tenant/select')

    expect(router.currentRoute.value.name).toBe('tenant-select')
  })

  it('redirects users with no memberships from tenant pages to onboarding', async () => {
    const session = useSessionStore()
    session.$patch({ user: { id: 'uid-1', email: 'owner@example.com' } as any, memberships: [] })

    await router.push('/t/tenant-a/mappings')

    expect(router.currentRoute.value.name).toBe('tenant-onboarding')
  })

  it('redirects tenant mismatch routes to tenant select', async () => {
    const session = useSessionStore()
    session.$patch({
      user: { id: 'uid-1', email: 'owner@example.com' } as any,
      memberships: [{ tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner' }],
    })
    session.activeTenantSlug = 'tenant-a'

    await router.push('/t/tenant-b/mappings')

    expect(router.currentRoute.value.name).toBe('tenant-select')
  })
})

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { beforeEach, describe, expect, it, vi } from 'vitest'
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
    session.$patch({
      user: { id: 'uid-1', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [],
    })

    await router.push('/tenant/select')

    expect(router.currentRoute.value.name).toBe('tenant-select')
  })

  it('redirects users with no memberships from tenant pages to onboarding', async () => {
    const session = useSessionStore()
    session.$patch({
      user: { id: 'uid-1', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [],
    })

    await router.push('/t/tenant-a/mappings')

    expect(router.currentRoute.value.name).toBe('tenant-onboarding')
  })

  it('redirects tenant mismatch routes to tenant select', async () => {
    const session = useSessionStore()
    session.$patch({
      user: { id: 'uid-1', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [{ tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner' }],
    })
    session.activeTenantSlug = 'tenant-a'

    await router.push('/t/tenant-b/mappings')

    expect(router.currentRoute.value.name).toBe('tenant-select')
  })

  it('does not bootstrap the session when navigating to auth-reset', async () => {
    // PG-186: a fresh recovery session created via verifyOtp() right before
    // this navigation must survive it -- bootstrap()'s backend session-sync
    // call has nothing to do with setting a new password and its failure
    // path signs the user straight back out.
    const session = useSessionStore()
    const bootstrapSpy = vi.spyOn(session, 'bootstrap')

    await router.push('/auth/reset')

    expect(bootstrapSpy).not.toHaveBeenCalled()
    expect(router.currentRoute.value.name).toBe('auth-reset')
  })

  it('still bootstraps the session for routes without skipBootstrap', async () => {
    const session = useSessionStore()
    const bootstrapSpy = vi.spyOn(session, 'bootstrap')

    await router.push('/reset-password')

    expect(bootstrapSpy).toHaveBeenCalled()
  })

  it('redirects a paused tenant to the paused page instead of its dashboard', async () => {
    const session = useSessionStore()
    session.$patch({
      user: { id: 'uid-1', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [
        { tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner', status: 'paused' },
      ],
    })

    await router.push('/t/tenant-a/mappings')

    expect(router.currentRoute.value.name).toBe('tenant-paused')
    expect(router.currentRoute.value.params.tenantSlug).toBe('tenant-a')
  })

  it('keeps plans and preferences reachable once the subscription lapsed (PG-298)', async () => {
    // Hosted builds only: the self-hosted router has no plans page and no
    // subscription lifecycle (PG-240), so the paused page is all it needs.
    if (!router.hasRoute('plans')) return
    const session = useSessionStore()
    session.$patch({
      user: { id: 'uid-1', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [
        { tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner', status: 'paused' },
      ],
      billing: {
        plan: 'solo',
        downgrade_detected_at: null,
        grace_period_ends_at: null,
        payment_failed_detected_at: null,
        cancellation_detected_at: '2026-08-01T00:00:00Z',
        subscription_grace_ends_at: '2026-08-31T00:00:00Z',
        lapsed_at: '2026-09-01T00:00:00Z',
      },
    })

    await router.push('/t/tenant-a/preferences')
    expect(router.currentRoute.value.name).toBe('preferences')

    await router.push('/t/tenant-a/plans')
    expect(router.currentRoute.value.name).toBe('plans')

    await router.push('/t/tenant-a/mappings')
    expect(router.currentRoute.value.name).toBe('tenant-paused')
  })

  it('does not open preferences for a workspace paused by a plan limit', async () => {
    const session = useSessionStore()
    session.$patch({
      user: { id: 'uid-1', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [
        { tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner', status: 'paused' },
      ],
      billing: {
        plan: 'solo',
        downgrade_detected_at: null,
        grace_period_ends_at: null,
        payment_failed_detected_at: null,
        cancellation_detected_at: null,
        subscription_grace_ends_at: null,
        lapsed_at: null,
      },
    })

    await router.push('/t/tenant-a/preferences')

    expect(router.currentRoute.value.name).toBe('tenant-paused')
  })

  it('lets navigation into the paused page itself proceed without looping', async () => {
    const session = useSessionStore()
    session.$patch({
      user: { id: 'uid-1', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [
        { tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner', status: 'paused' },
      ],
    })

    await router.push('/t/tenant-a/paused')

    expect(router.currentRoute.value.name).toBe('tenant-paused')
  })
})

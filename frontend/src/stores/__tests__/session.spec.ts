// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: vi.fn(),
      signOut: vi.fn(),
    },
    from: vi.fn(),
  },
}))

import { supabase } from '../../lib/supabase'
import { useSessionStore } from '../session'

describe('session store', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('returns false from bootstrap when no session exists', async () => {
    vi.mocked(supabase.auth.getSession).mockResolvedValue({
      data: { session: null },
      error: null,
    } as any)

    const store = useSessionStore()
    const result = await store.bootstrap()

    expect(result).toBe(false)
    expect(store.idToken).toBeNull()
    expect(store.isAuthenticated).toBe(false)
  })

  it('clears session state on clearSession', () => {
    const store = useSessionStore()
    store.$patch({ user: { id: 'uid-1', email: 'test@example.com' } as any })

    store.clearSession()

    expect(store.user).toBeNull()
    expect(store.idToken).toBeNull()
    expect(store.memberships).toEqual([])
  })
})

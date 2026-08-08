// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// Where identity comes from (PG-237). The point of these is that the two modes
// are interchangeable from the outside, and that the one which keeps its own
// accounts never reaches for an SDK that is not there.

import { beforeEach, describe, expect, it, vi } from 'vitest'

// vi.mock is hoisted above everything, so the doubles have to be created
// inside the factory and reached through vi.mocked afterwards.
vi.mock('../supabase', () => ({
  supabaseConfigured: true,
  supabase: {
    auth: {
      getSession: vi.fn(),
      signOut: vi.fn(),
      signInWithPassword: vi.fn(),
      onAuthStateChange: vi.fn(),
    },
  },
}))

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn() } }))

import { api } from '../api'
import { supabase } from '../supabase'

const getSessionMock = vi.mocked(supabase.auth.getSession)
const signOutMock = vi.mocked(supabase.auth.signOut)
const signInWithPasswordMock = vi.mocked(supabase.auth.signInWithPassword)
const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

import {
  authMode,
  capabilities,
  detectAuthMode,
  getSession,
  installationNeedsSetup,
  signInWithPassword,
  signOut,
} from '../authProvider'

const LOCAL_KEY = 'payglue.local.session'

const goLocal = async (needsSetup = false) => {
  apiGet.mockResolvedValue({ data: { enabled: true, needs_setup: needsSetup } })
  await detectAuthMode()
}

const goHosted = async () => {
  apiGet.mockResolvedValue({ data: { enabled: false, needs_setup: false } })
  await detectAuthMode()
}

describe('which provider is in charge', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('follows what the backend reports, not what the build assumed', async () => {
    await goLocal()
    expect(authMode()).toBe('local')

    await goHosted()
    expect(authMode()).toBe('supabase')
  })

  it('falls back to the hosted path when the backend has no such route', async () => {
    // An older backend answers 404. That is not a failure, it just means the
    // installation predates local accounts.
    apiGet.mockRejectedValue(new Error('404'))
    await detectAuthMode()
    expect(authMode()).toBe('supabase')
  })

  it('reports a setup-needed installation only while it has no account', async () => {
    await goLocal(true)
    expect(installationNeedsSetup()).toBe(true)

    await goLocal(false)
    expect(installationNeedsSetup()).toBe(false)
  })

  it('offers no authenticator app where there is none to offer', async () => {
    await goLocal()
    expect(capabilities()).toMatchObject({
      mfa: false,
      oauth: false,
      magicLink: false,
      passwordSignIn: true,
    })

    await goHosted()
    expect(capabilities()).toMatchObject({ mfa: true, oauth: true, magicLink: true })
  })
})

describe('accounts on this server', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    localStorage.clear()
    await goLocal()
  })

  it('signing in stores a session the rest of the app can read back', async () => {
    apiPost.mockResolvedValue({
      data: {
        access_token: 'token-abc',
        expires_at: Math.floor(Date.now() / 1000) + 3600,
        user: { id: 'local:1', email: 'owner@example.com' },
      },
    })

    const session = await signInWithPassword('owner@example.com', 'a-real-password')
    expect(session.accessToken).toBe('token-abc')
    expect(await getSession()).toMatchObject({
      accessToken: 'token-abc',
      email: 'owner@example.com',
    })
    // The hosted SDK must not have been touched at all.
    expect(signInWithPasswordMock).not.toHaveBeenCalled()
  })

  it('an expired token is not offered as a session', async () => {
    localStorage.setItem(
      LOCAL_KEY,
      JSON.stringify({
        accessToken: 'stale',
        userId: 'local:1',
        email: 'owner@example.com',
        expiresAt: Math.floor(Date.now() / 1000) - 60,
      }),
    )
    expect(await getSession()).toBeNull()
    expect(localStorage.getItem(LOCAL_KEY)).toBeNull()
  })

  it('rubbish in storage is treated as no session rather than crashing', async () => {
    localStorage.setItem(LOCAL_KEY, 'not json')
    expect(await getSession()).toBeNull()
  })

  it('signing out forgets the token without calling anywhere', async () => {
    localStorage.setItem(
      LOCAL_KEY,
      JSON.stringify({
        accessToken: 't',
        userId: 'local:1',
        email: 'owner@example.com',
        expiresAt: Math.floor(Date.now() / 1000) + 3600,
      }),
    )
    await signOut()
    expect(await getSession()).toBeNull()
    expect(signOutMock).not.toHaveBeenCalled()
  })
})

describe('the hosted path is unchanged', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    localStorage.clear()
    await goHosted()
  })

  it('reads the session from the SDK', async () => {
    // Only the three fields the adapter reads; the full User type is a lot of
    // shape for no extra assurance. Same idiom as session.spec.ts.
    getSessionMock.mockResolvedValue({
      data: {
        session: {
          access_token: 'supabase-token',
          user: { id: 'uuid-1', email: 'someone@example.com' },
        },
      },
    } as any)
    expect(await getSession()).toEqual({
      accessToken: 'supabase-token',
      userId: 'uuid-1',
      email: 'someone@example.com',
    })
  })

  it('signs out through the SDK', async () => {
    signOutMock.mockResolvedValue({ error: null })
    await signOut()
    expect(signOutMock).toHaveBeenCalledOnce()
    // And never writes the local key, which would outlive the hosted session.
    expect(localStorage.getItem(LOCAL_KEY)).toBeNull()
  })
})

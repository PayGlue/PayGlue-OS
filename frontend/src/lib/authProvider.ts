// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// Where identity comes from (PG-237).
//
// Two implementations behind one small interface: a hosted provider, or
// accounts kept by the installation itself. The rest of the application asks
// this module rather than reaching for a specific SDK, so the difference
// stops at this file.
//
// The interface is deliberately NOT the union of everything both can do. It
// is the part the application actually uses, plus a `capabilities` object for
// the parts only one of them has. A screen that offers an authenticator app
// asks `capabilities.mfa` and leaves the section out otherwise, the same way
// the settings navigation asks `router.hasRoute()`. Asking beats forking.

import { api } from './api'
import { supabase, supabaseConfigured } from './supabase'

export type AuthMode = 'supabase' | 'local'

export interface AuthCapabilities {
  /** Sign in with a link sent by email. */
  magicLink: boolean
  /** Sign in with Google or GitHub, and link/unlink those afterwards. */
  oauth: boolean
  /** Authenticator apps. Django has no equivalent, so local mode has none. */
  mfa: boolean
  /** Change the address the account signs in with. */
  emailChange: boolean
  /** Sign in with a password. */
  passwordSignIn: boolean
}

export interface AuthSession {
  accessToken: string
  userId: string
  email: string
}

const STORAGE_KEY = 'payglue.local.session'

/**
 * True when this installation keeps its own accounts.
 *
 * Decided by what the backend reports, not by the frontend build: the
 * dashboard and the API can be deployed separately, and the API is the one
 * that knows. Read once at startup by `detectAuthMode()`.
 */
let mode: AuthMode = supabaseConfigured ? 'supabase' : 'local'
let needsSetup = false

export const authMode = (): AuthMode => mode
export const installationNeedsSetup = (): boolean => needsSetup

export const capabilities = (): AuthCapabilities =>
  mode === 'supabase'
    ? {
        magicLink: true,
        oauth: true,
        mfa: true,
        emailChange: true,
        passwordSignIn: true,
      }
    : {
        magicLink: false,
        oauth: false,
        mfa: false,
        emailChange: false,
        passwordSignIn: true,
      }

/**
 * Asks the backend which way it signs people in.
 *
 * Called once before the router starts. A backend with local accounts also
 * says whether it has any account yet, which is the only moment the setup
 * wizard may appear.
 */
export const detectAuthMode = async (): Promise<void> => {
  try {
    const { data } = await api.get<{ enabled: boolean; needs_setup: boolean }>(
      '/api/v1/auth/local/status',
    )
    if (data?.enabled) {
      mode = 'local'
      needsSetup = Boolean(data.needs_setup)
      return
    }
  } catch {
    // An older backend has no such route. That is not an error, it just means
    // the hosted path, which is what the build already assumed.
  }
  mode = supabaseConfigured ? 'supabase' : 'local'
  needsSetup = false
}

// -- local session storage ---------------------------------------------------
//
// The token is a plain bearer token from our own backend, kept where the
// Supabase SDK keeps its own: localStorage. Same exposure, same trade-off, and
// choosing differently here would only mean the two modes lose their sessions
// under different circumstances.

interface StoredLocalSession {
  accessToken: string
  userId: string
  email: string
  expiresAt: number
}

const readLocal = (): StoredLocalSession | null => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredLocalSession
    if (!parsed?.accessToken) return null
    // Expiry is checked here as well as at the backend, so an obviously dead
    // token never costs a round trip.
    if (parsed.expiresAt && parsed.expiresAt * 1000 < Date.now()) {
      localStorage.removeItem(STORAGE_KEY)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

const writeLocal = (s: StoredLocalSession): void => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
}

const clearLocal = (): void => {
  localStorage.removeItem(STORAGE_KEY)
}

interface LocalTokenResponse {
  access_token: string
  expires_at: number
  user: { id: string; email: string }
}

const storeLocalToken = (data: LocalTokenResponse): AuthSession => {
  const session: StoredLocalSession = {
    accessToken: data.access_token,
    userId: data.user.id,
    email: data.user.email,
    expiresAt: data.expires_at,
  }
  writeLocal(session)
  notify('SIGNED_IN')
  return { accessToken: session.accessToken, userId: session.userId, email: session.email }
}

// -- change notification -----------------------------------------------------

type AuthEvent = 'SIGNED_IN' | 'SIGNED_OUT' | 'TOKEN_REFRESHED'
type Listener = (event: AuthEvent) => void

const listeners = new Set<Listener>()

const notify = (event: AuthEvent): void => {
  for (const listener of listeners) listener(event)
}

/** Returns the unsubscribe function, in both modes. */
export const onAuthStateChange = (listener: Listener): (() => void) => {
  if (mode === 'supabase') {
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'SIGNED_IN' || event === 'SIGNED_OUT' || event === 'TOKEN_REFRESHED') {
        listener(event)
      }
    })
    return () => subscription.unsubscribe()
  }
  listeners.add(listener)
  return () => listeners.delete(listener)
}

// -- the operations the application uses -------------------------------------

export const getSession = async (): Promise<AuthSession | null> => {
  if (mode === 'supabase') {
    const { data } = await supabase.auth.getSession()
    if (!data.session) return null
    return {
      accessToken: data.session.access_token,
      userId: data.session.user.id,
      email: data.session.user.email ?? '',
    }
  }
  const stored = readLocal()
  if (!stored) return null
  return { accessToken: stored.accessToken, userId: stored.userId, email: stored.email }
}

export const signOut = async (): Promise<void> => {
  if (mode === 'supabase') {
    await supabase.auth.signOut()
    return
  }
  // Nothing to call: the token is short-lived, and the thing a sign-out has to
  // guarantee, that a stolen token stops working once the password changes,
  // is handled by the backend comparing a fingerprint of the password hash.
  clearLocal()
  notify('SIGNED_OUT')
}

export const signInWithPassword = async (
  email: string,
  password: string,
): Promise<AuthSession> => {
  if (mode === 'supabase') {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password })
    if (error || !data.session) throw new Error(error?.message ?? 'Sign in failed.')
    return {
      accessToken: data.session.access_token,
      userId: data.session.user.id,
      email: data.session.user.email ?? email,
    }
  }
  const { data } = await api.post<LocalTokenResponse>('/api/v1/auth/local/token', {
    email,
    password,
  })
  return storeLocalToken(data)
}

/** Creates the first account. Local mode only, and only while there is none. */
export const bootstrapFirstAccount = async (
  email: string,
  password: string,
): Promise<AuthSession> => {
  const { data } = await api.post<LocalTokenResponse>('/api/v1/auth/local/bootstrap', {
    email,
    password,
  })
  needsSetup = false
  return storeLocalToken(data)
}

export const requestPasswordReset = async (email: string, redirectTo?: string): Promise<void> => {
  if (mode === 'supabase') {
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo })
    if (error) throw new Error(error.message)
    return
  }
  await api.post('/api/v1/auth/local/password/reset', { email })
}

export const confirmPasswordReset = async (
  id: string,
  token: string,
  newPassword: string,
): Promise<AuthSession> => {
  const { data } = await api.post<LocalTokenResponse>(
    '/api/v1/auth/local/password/reset/confirm',
    { id, token, new_password: newPassword },
  )
  return storeLocalToken(data)
}

export const changePassword = async (
  currentPassword: string,
  newPassword: string,
): Promise<void> => {
  if (mode === 'supabase') {
    const { error } = await supabase.auth.updateUser({ password: newPassword })
    if (error) throw new Error(error.message)
    return
  }
  const { data } = await api.post<LocalTokenResponse>('/api/v1/auth/local/password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
  // The backend retires every token issued before the change, including the
  // one this request was made with, and hands back a fresh one. Storing it is
  // what keeps the person signed in in the tab they are standing in.
  storeLocalToken(data)
}

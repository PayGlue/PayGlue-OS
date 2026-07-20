// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { supabase } from '../lib/supabase'
import { getTenantWebhookSecret, postAuthSession } from '../lib/api'
import type { User } from '@supabase/supabase-js'
import type { SessionBillingInfo } from '../types/api'

const STORAGE_KEY = 'payglue-session'

interface PersistedSession {
  activeTenantSlug: string | null
}

const loadPersisted = (): PersistedSession | null => {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as PersistedSession
    return {
      activeTenantSlug:
        typeof parsed.activeTenantSlug === 'string' ? parsed.activeTenantSlug : null,
    }
  } catch {
    return null
  }
}

interface TenantMembership {
  tenant_id: string
  tenant_slug: string
  tenant_name: string
  role: string
  status: string
}

export const useSessionStore = defineStore('session', () => {
  const persisted = loadPersisted()
  const user = ref<User | null>(null)
  const accessToken = ref<string | null>(null)
  const memberships = ref<TenantMembership[]>([])
  const activeTenantSlug = ref<string | null>(persisted?.activeTenantSlug ?? null)
  const isLoading = ref(false)
  const errorMessage = ref<string | null>(null)
  // PG-141: set when the account is inside a post-downgrade grace period.
  // Null once the customer upgrades back or after enforcement has already
  // paused the excess tenants (the backend clears downgrade_detected_at
  // either way, so this naturally disappears -- no separate dismissal
  // needed).
  const billing = ref<SessionBillingInfo | null>(null)

  const idToken = computed(() => accessToken.value ?? null)
  const isAuthenticated = computed(() => Boolean(user.value))
  const activeMembership = computed(() =>
    memberships.value.find((m) => m.tenant_slug === activeTenantSlug.value) ?? null,
  )

  const persist = () => {
    if (!user.value) {
      localStorage.removeItem(STORAGE_KEY)
      return
    }
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ activeTenantSlug: activeTenantSlug.value }),
    )
  }

  const bootstrap = async () => {
    isLoading.value = true
    errorMessage.value = null
    try {
      const { data: sessionData } = await supabase.auth.getSession()
      if (!sessionData.session) {
        clearSession()
        return false
      }
      user.value = sessionData.session.user
      accessToken.value = sessionData.session.access_token

      let authSession
      try {
        authSession = await postAuthSession(sessionData.session.access_token)
      } catch (error) {
        // A valid Supabase session with no PayGlue account behind it (e.g. an
        // uninvited OAuth sign-in) -- the backend invite gate rejects this.
        // Sign out of Supabase too, otherwise bootstrap() would keep retrying
        // and failing on every route guard check with the user stuck looking
        // "logged in" but unable to do anything.
        await supabase.auth.signOut()
        clearSession()
        errorMessage.value =
          error instanceof Error ? error.message : 'This account has no PayGlue access yet.'
        return false
      }

      memberships.value = authSession.memberships.map((row) => ({
        tenant_id: '',
        tenant_slug: row.tenant_slug,
        tenant_name: row.tenant_slug,
        role: row.role,
        status: row.status,
      }))
      billing.value = authSession.billing

      if (
        activeTenantSlug.value &&
        !memberships.value.some((m) => m.tenant_slug === activeTenantSlug.value)
      ) {
        activeTenantSlug.value = null
      }
      if (!activeTenantSlug.value && memberships.value.length > 0) {
        // Prefer an active tenant over a paused one for the default
        // selection -- alphabetical order alone could otherwise land the
        // user straight in a paused workspace on first load.
        const firstActive = memberships.value.find((m) => m.status === 'active')
        activeTenantSlug.value = (firstActive ?? memberships.value[0])?.tenant_slug ?? null
      }
      persist()
      return true
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : 'Unable to load session.'
      return false
    } finally {
      isLoading.value = false
    }
  }

  const setActiveTenant = (tenantSlug: string) => {
    activeTenantSlug.value = tenantSlug
    persist()
  }

  // Every Connection{Provider}View independently called getTenantWebhookSecret
  // on its own mount -- same tenant-level value, refetched up to 7x per
  // tenant session, each with its own silently-swallowed error handling. That
  // made the webhook URL's &key= param intermittently render empty (whichever
  // tab's own fetch happened to be slow/racing at the moment), inconsistent
  // across tabs for the exact same underlying value. Centralized here: fetch
  // once per tenant, cache, share across every view.
  const webhookSecret = ref<string | null>(null)
  let webhookSecretPromise: Promise<string> | null = null
  let webhookSecretTenant: string | null = null

  const getWebhookSecret = async (): Promise<string> => {
    const tenantSlug = activeTenantSlug.value
    const token = idToken.value
    if (!tenantSlug || !token) return ''
    if (webhookSecretTenant !== tenantSlug) {
      webhookSecretTenant = tenantSlug
      webhookSecret.value = null
      webhookSecretPromise = null
    }
    if (webhookSecret.value) return webhookSecret.value
    if (!webhookSecretPromise) {
      webhookSecretPromise = getTenantWebhookSecret(tenantSlug, token)
        .then((res) => {
          webhookSecret.value = res.webhook_secret
          return res.webhook_secret
        })
        .catch(() => {
          webhookSecretPromise = null
          return ''
        })
    }
    return webhookSecretPromise
  }

  const clearSession = (options?: { preserveError?: boolean }) => {
    user.value = null
    accessToken.value = null
    memberships.value = []
    activeTenantSlug.value = null
    billing.value = null
    if (!options?.preserveError) errorMessage.value = null
    persist()
  }

  const signOut = async () => {
    await supabase.auth.signOut()
    clearSession()
  }

  return {
    idToken,
    accessToken,
    user,
    memberships,
    activeTenantSlug,
    activeMembership,
    isLoading,
    errorMessage,
    isAuthenticated,
    billing,
    webhookSecret,
    getWebhookSecret,
    bootstrap,
    setActiveTenant,
    clearSession,
    signOut,
  }
})

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { supabase } from '../lib/supabase'
import { api } from '../lib/api'
import type { User } from '@supabase/supabase-js'

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
}

interface DjangoMembershipRow {
  tenant_slug: string
  role: string
}

export const useSessionStore = defineStore('session', () => {
  const persisted = loadPersisted()
  const user = ref<User | null>(null)
  const accessToken = ref<string | null>(null)
  const memberships = ref<TenantMembership[]>([])
  const activeTenantSlug = ref<string | null>(persisted?.activeTenantSlug ?? null)
  const isLoading = ref(false)
  const errorMessage = ref<string | null>(null)

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

      const { data: memberRows } = await api.get<DjangoMembershipRow[]>(
        '/api/v1/tenants',
        { headers: { Authorization: `Bearer ${sessionData.session.access_token}` } },
      )

      memberships.value = (memberRows ?? []).map((row) => ({
        tenant_id: '',
        tenant_slug: row.tenant_slug,
        tenant_name: row.tenant_slug,
        role: row.role,
      }))

      if (
        activeTenantSlug.value &&
        !memberships.value.some((m) => m.tenant_slug === activeTenantSlug.value)
      ) {
        activeTenantSlug.value = null
      }
      if (!activeTenantSlug.value && memberships.value.length > 0) {
        activeTenantSlug.value = memberships.value[0]?.tenant_slug ?? null
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

  const clearSession = (options?: { preserveError?: boolean }) => {
    user.value = null
    accessToken.value = null
    memberships.value = []
    activeTenantSlug.value = null
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
    bootstrap,
    setActiveTenant,
    clearSession,
    signOut,
  }
})

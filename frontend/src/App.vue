// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { supabase } from './lib/supabase'
import { useSessionStore } from './stores/session'
import { appBaseUrl } from './lib/publicUrls'

const router = useRouter()
const route = useRoute()
const session = useSessionStore()

// PG-232: switching publication pushes the same named route with a different
// :tenantSlug. Vue reuses the component for that, so onMounted never runs
// again and every view that loads its data there keeps showing the previous
// publication until a manual reload. Keying the view on the slug remounts it,
// which fixes all of them at once rather than adding a watcher per view.
const tenantViewKey = computed(() => {
  const slug = route.params.tenantSlug
  return typeof slug === 'string' ? `t:${slug}` : 'no-tenant'
})

let unsubscribe: (() => void) | null = null

onMounted(() => {
  const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, supabaseSession) => {
    if ((event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED') && supabaseSession) {
      await session.bootstrap()
      if (event === 'SIGNED_IN') {
        // Was a literal host, so a self-hosted dashboard never redirected to
        // the tenant picker after sign-in (PG-238). The dashboard is by
        // definition served from its own origin, so comparing against the
        // configured app origin is both correct and portable.
        const isAppSubdomain = appBaseUrl() === '' || window.location.origin === appBaseUrl() || window.location.hostname === 'localhost'
        const currentName = router.currentRoute.value.name
        if (isAppSubdomain && (currentName === 'landing' || currentName === 'login' || currentName === 'auth-callback')) {
          await router.replace({ name: 'tenant-select' })
        }
      }
    }
    if (event === 'SIGNED_OUT' && router.currentRoute.value.meta.requiresAuth) {
      session.clearSession()
      router.replace({ name: 'login' })
    }
  })
  unsubscribe = () => subscription.unsubscribe()
})

onUnmounted(() => {
  unsubscribe?.()
})
</script>

<template>
  <RouterView :key="tenantViewKey" />
</template>

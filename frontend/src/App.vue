// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { supabase } from './lib/supabase'
import { useSessionStore } from './stores/session'

const router = useRouter()
const session = useSessionStore()

let unsubscribe: (() => void) | null = null

onMounted(() => {
  const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, supabaseSession) => {
    if ((event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED') && supabaseSession) {
      await session.bootstrap()
      if (event === 'SIGNED_IN') {
        const isAppSubdomain = window.location.hostname === 'app.payglue.io' || window.location.hostname === 'localhost'
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
  <RouterView />
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { supabase } from '../lib/supabase'

const router = useRouter()

onMounted(async () => {
  // Exchange the code/token from the URL (PKCE flow or magic link hash)
  const { data, error } = await supabase.auth.exchangeCodeForSession(window.location.href)
  if (error || !data.session) {
    // Fallback: check if session already exists (e.g. hash-based flow handled by client)
    const { data: existing } = await supabase.auth.getSession()
    if (!existing.session) {
      router.replace({ name: 'login' })
      return
    }
  }
  router.replace({ name: 'tenant-select' })
})
</script>

<template>
  <main class="flex min-h-screen items-center justify-center bg-white">
    <p class="text-sm text-slate-500">Signing you in...</p>
  </main>
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'

const router = useRouter()
const session = useSessionStore()

onMounted(async () => {
  if (!session.isAuthenticated) {
    await router.replace({ name: 'login' })
    return
  }

  if (session.activeTenantSlug) {
    await router.replace(`/t/${session.activeTenantSlug}/dashboard`)
    return
  }

  if (session.memberships.length > 0) {
    await router.replace('/tenant/select')
    return
  }

  await router.replace('/tenant/create')
})
</script>

<template>
  <div class="grid min-h-screen place-items-center bg-slate-50 px-4">
    <p class="text-sm text-slate-500">Preparing your dashboard...</p>
  </div>
</template>

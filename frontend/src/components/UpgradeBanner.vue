// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '../stores/session'

defineProps<{
  message: string
  planKey: string | null
}>()

const session = useSessionStore()
const plansUrl = computed(() =>
  session.activeTenantSlug ? `/t/${session.activeTenantSlug}/plans` : null,
)
</script>

<template>
  <div class="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
    <p>{{ message }}</p>
    <RouterLink
      v-if="plansUrl"
      :to="plansUrl"
      class="mt-2 inline-flex items-center gap-1.5 rounded-full bg-amber-600 px-3 py-1.5 font-semibold text-white hover:opacity-90"
    >
      View plans and pricing →
    </RouterLink>
  </div>
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { useSessionStore } from '../stores/session'

const route = useRoute()
const session = useSessionStore()

const tenantSlug = computed(() => String(route.params.tenantSlug ?? ''))
const displayName = computed(() =>
  tenantSlug.value
    .split(/[-_]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' '),
)
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-lg py-12 text-center">
      <div class="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-full bg-amber-100">
        <svg class="h-6 w-6 text-amber-600" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-8.25 3h.008v.008h-.008v-.008z" />
        </svg>
      </div>
      <h1 class="text-xl font-semibold text-slate-900">{{ displayName }} is paused</h1>
      <p class="mt-2 text-sm text-slate-500">
        This workspace went over your current plan's limit after your last downgrade, so it's paused. It stopped processing new webhooks, and nothing here is reachable right now. Nothing was deleted.
      </p>
      <p class="mt-2 text-sm text-slate-500">
        Upgrade your plan to reactivate it, or leave it paused and switch to one of your active workspaces.
      </p>
      <div class="mt-6 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
        <RouterLink
          :to="session.activeTenantSlug && session.activeTenantSlug !== tenantSlug ? `/t/${session.activeTenantSlug}/plans` : '/tenant/select'"
          class="inline-flex items-center gap-1.5 rounded-full bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
        >
          View plans and pricing
        </RouterLink>
        <RouterLink
          to="/tenant/select"
          class="inline-flex items-center gap-1.5 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
        >
          Switch workspace
        </RouterLink>
      </div>
    </div>
  </AppShell>
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()

// PG-141: downgrade_detected_at/grace_period_ends_at come from the same
// AuthSessionView payload that populates memberships -- no separate fetch.
// null once the customer upgrades back, or once enforce_downgrade_grace_periods
// has already paused the excess tenants and cleared the flag server-side.
const daysLeft = computed(() => {
  const endsAt = session.billing?.grace_period_ends_at
  if (!endsAt) return null
  const msLeft = new Date(endsAt).getTime() - Date.now()
  return Math.max(0, Math.ceil(msLeft / (24 * 60 * 60 * 1000)))
})

const plansUrl = computed(() =>
  session.activeTenantSlug ? `/t/${session.activeTenantSlug}/plans` : '/tenant/select',
)
</script>

<template>
  <div
    v-if="daysLeft !== null"
    class="mb-4 flex flex-col gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between"
  >
    <p>
      <span class="font-semibold">{{ daysLeft }} {{ daysLeft === 1 ? 'day' : 'days' }} left</span>
      on your grace period. Your workspaces stay fully active until then. After that, the newest ones beyond your plan's limit will be paused (not deleted) unless you upgrade back.
    </p>
    <RouterLink
      :to="plansUrl"
      class="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90"
    >
      View plans and pricing →
    </RouterLink>
  </div>
</template>

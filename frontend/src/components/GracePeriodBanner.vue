// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()
const router = useRouter()

// PG-141: downgrade_detected_at/grace_period_ends_at come from the same
// AuthSessionView payload that populates memberships -- no separate fetch.
// null once the customer upgrades back, or once enforce_downgrade_grace_periods
// has already paused the excess tenants and cleared the flag server-side.
const daysUntil = (endsAt: string | null | undefined): number | null => {
  if (!endsAt) return null
  const msLeft = new Date(endsAt).getTime() - Date.now()
  return Math.max(0, Math.ceil(msLeft / (24 * 60 * 60 * 1000)))
}

const daysLeft = computed(() => daysUntil(session.billing?.grace_period_ends_at))

// PG-298: the grace period after a subscription ended, whether the customer
// cancelled or the card stopped working. Access stays complete until the
// date; after it the workspaces are paused, not deleted. Once lapsed_at is
// set the paused page carries the message instead, so this stays quiet.
const subscriptionDaysLeft = computed(() => {
  if (session.billing?.lapsed_at) return null
  return daysUntil(session.billing?.subscription_grace_ends_at)
})

// null where there is no price list: a self-hosted build has no plans route
// (PG-240). The countdown still shows, only the button goes away.
const plansUrl = computed(() => {
  if (!router.hasRoute('plans')) return null
  return session.activeTenantSlug ? `/t/${session.activeTenantSlug}/plans` : '/tenant/select'
})
</script>

<template>
  <div
    v-if="subscriptionDaysLeft !== null"
    class="mb-4 flex flex-col gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900 sm:flex-row sm:items-center sm:justify-between"
  >
    <p>
      <span class="font-semibold">{{ subscriptionDaysLeft }} {{ subscriptionDaysLeft === 1 ? 'day' : 'days' }} left</span>
      on your grace period. Your subscription has ended, but we know things get tough sometimes, so everything stays fully active until then. After that your workspaces are paused, not deleted, until you pick a plan again.
    </p>
    <RouterLink
      v-if="plansUrl"
      :to="plansUrl"
      class="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90"
    >
      Pick a plan →
    </RouterLink>
  </div>
  <div
    v-else-if="daysLeft !== null"
    class="mb-4 flex flex-col gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between"
  >
    <p>
      <span class="font-semibold">{{ daysLeft }} {{ daysLeft === 1 ? 'day' : 'days' }} left</span>
      on your grace period. Your workspaces stay fully active until then. After that, the newest ones beyond your plan's limit will be paused (not deleted) unless you upgrade back.
    </p>
    <RouterLink
      v-if="plansUrl"
      :to="plansUrl"
      class="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90"
    >
      View plans and pricing →
    </RouterLink>
  </div>
</template>

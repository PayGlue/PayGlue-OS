// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { useSessionStore } from '../stores/session'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const tenantSlug = computed(() => String(route.params.tenantSlug ?? ''))
const displayName = computed(() =>
  tenantSlug.value
    .split(/[-_]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' '),
)

// PG-298: paused because the subscription lapsed, not because of a plan
// limit. Every workspace is paused then, so the plans page is reached
// through this very workspace (the router lets that through) and the copy
// says what actually happened.
const lapsed = computed(() => Boolean(session.billing?.lapsed_at))

// null in a self-hosted build, which has no price list to upgrade on
// (PG-240). The explanation of why the workspace is paused still stands;
// only the button that would lead nowhere is dropped.
const plansUrl = computed(() => {
  if (!router.hasRoute('plans')) return null
  if (lapsed.value) return `/t/${tenantSlug.value}/plans`
  return session.activeTenantSlug && session.activeTenantSlug !== tenantSlug.value
    ? `/t/${session.activeTenantSlug}/plans`
    : '/tenant/select'
})

const preferencesUrl = computed(() => `/t/${tenantSlug.value}/preferences`)

// PG-303: a paused account is deleted after three months. The date is
// derived here from lapsed_at rather than sent by the backend, so the
// session payload stays what it is; the constant matches
// tenants/lapse.DELETE_AFTER_PAUSED_DAYS.
const DELETE_AFTER_PAUSED_DAYS = 90
const deletionDate = computed(() => {
  const lapsedAt = session.billing?.lapsed_at
  if (!lapsedAt) return null
  const date = new Date(lapsedAt)
  date.setDate(date.getDate() + DELETE_AFTER_PAUSED_DAYS)
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
})
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
      <template v-if="lapsed">
        <p class="mt-2 text-sm text-slate-500">
          Your PayGlue subscription ended and the 30-day grace period is over, so your workspaces are paused. Purchases at your payment provider no longer unlock anything in Ghost. Nothing was deleted: your connections, mappings, paywalls and buttons are all still here.
        </p>
        <p class="mt-2 text-sm text-slate-500">
          Pick a plan and everything picks up where it left off. If you are done with PayGlue, you can delete your account from the account settings.
        </p>
        <p v-if="deletionDate" class="mt-2 text-sm text-slate-500">
          Paused accounts are kept for three months. Without a plan, this account is deleted on {{ deletionDate }}.
        </p>
        <div class="mt-6 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
          <RouterLink
            v-if="plansUrl"
            :to="plansUrl"
            class="inline-flex items-center gap-1.5 rounded-full bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            Pick a plan
          </RouterLink>
          <RouterLink
            :to="preferencesUrl"
            class="inline-flex items-center gap-1.5 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Account settings
          </RouterLink>
        </div>
      </template>
      <template v-else>
        <p class="mt-2 text-sm text-slate-500">
          This workspace went over your current plan's limit after your last downgrade, so it's paused. It stopped processing new webhooks, and nothing here is reachable right now. Nothing was deleted.
        </p>
        <p class="mt-2 text-sm text-slate-500">
          Upgrade your plan to reactivate it, or leave it paused and switch to one of your active workspaces.
        </p>
        <div class="mt-6 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
          <RouterLink
            v-if="plansUrl"
            :to="plansUrl"
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
      </template>
    </div>
  </AppShell>
</template>

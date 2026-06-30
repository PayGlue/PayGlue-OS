// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import {
  getIntegrationConfig,
  listAuditEvents,
  listMappings,
  listTeamMembers,
  listWebhookEvents,
} from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { AuditEvent, ProductMapping, TeamMember, WebhookEvent } from '../types/api'

const session = useSessionStore()

const loading = ref(false)
const errorMessage = ref<string | null>(null)

const webhookEvents = ref<WebhookEvent[]>([])
const auditEvents = ref<AuditEvent[]>([])
const mappings = ref<ProductMapping[]>([])
const teamMembers = ref<TeamMember[]>([])

const paymentEnabled = ref(false)
const cmsEnabled = ref(false)

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) {
    throw new Error('Tenant context is missing.')
  }
  return { tenantSlug: session.activeTenantSlug, token: session.idToken }
}

const loadDashboard = async () => {
  loading.value = true
  errorMessage.value = null

  try {
    const { tenantSlug, token } = context()

    const [eventsResult, auditResult, mappingResult, teamResult, paymentResult, cmsResult] =
      await Promise.allSettled([
        listWebhookEvents(tenantSlug, token),
        listAuditEvents(tenantSlug, token),
        listMappings(tenantSlug, token),
        listTeamMembers(tenantSlug, token),
        getIntegrationConfig(tenantSlug, token, 'payment'),
        getIntegrationConfig(tenantSlug, token, 'cms'),
      ])

    if (eventsResult.status === 'fulfilled') webhookEvents.value = eventsResult.value
    if (auditResult.status === 'fulfilled') auditEvents.value = auditResult.value
    if (mappingResult.status === 'fulfilled') mappings.value = mappingResult.value
    if (teamResult.status === 'fulfilled') teamMembers.value = teamResult.value
    if (paymentResult.status === 'fulfilled') paymentEnabled.value = paymentResult.value.enabled
    if (cmsResult.status === 'fulfilled') cmsEnabled.value = cmsResult.value.enabled

    const failedParts = [
      eventsResult,
      auditResult,
      mappingResult,
      teamResult,
      paymentResult,
      cmsResult,
    ].filter((part) => part.status === 'rejected')

    if (failedParts.length > 0) {
      errorMessage.value = 'Some dashboard modules failed to load. Partial data is shown.'
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to load dashboard data.'
  } finally {
    loading.value = false
  }
}

const replayCandidates = computed(
  () => webhookEvents.value.filter((event) => event.status === 'failed' || event.status === 'dead_letter').length,
)

const failedEvents = computed(
  () => webhookEvents.value.filter((event) => event.status === 'failed' || event.status === 'dead_letter').length,
)

const processedToday = computed(
  () => webhookEvents.value.filter((event) => event.status === 'processed').length,
)

const recentWebhookEvents = computed(() => webhookEvents.value.slice(0, 6))
const recentAuditEvents = computed(() => auditEvents.value.slice(0, 6))

const formatDate = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

const thankYouKey = computed(() => `pg_ty_${session.activeTenantSlug}`)
const thankYouDismissed = ref(false)

const onboardingComplete = computed(
  () => paymentEnabled.value && cmsEnabled.value && mappings.value.length > 0,
)

const showThankYou = computed(
  () => onboardingComplete.value && !thankYouDismissed.value,
)

const dismissThankYou = () => {
  localStorage.setItem(thankYouKey.value, '1')
  thankYouDismissed.value = true
}

onMounted(async () => {
  thankYouDismissed.value = Boolean(localStorage.getItem(thankYouKey.value))
  await loadDashboard()
})
</script>

<template>
  <AppShell>
    <div class="space-y-6">

      <!-- Thank You banner (einmalig nach erstem Onboarding) -->
      <Transition
        enter-active-class="transition-all duration-500 ease-out"
        enter-from-class="opacity-0 -translate-y-2"
        leave-active-class="transition-all duration-300 ease-in"
        leave-to-class="opacity-0 -translate-y-2"
      >
        <div
          v-if="showThankYou"
          class="relative rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 to-white p-5 shadow-sm"
        >
          <button
            class="absolute right-4 top-4 text-slate-400 hover:text-slate-600"
            aria-label="Dismiss"
            @click="dismissThankYou"
          >
            <svg class="h-4 w-4" viewBox="0 0 16 16" fill="none"><path d="M3 3l10 10M13 3L3 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </button>
          <p class="mb-1 text-base font-semibold text-slate-900">You're in. Thank you for being one of the first.</p>
          <p class="max-w-xl text-sm text-slate-600">
            We built PayGlue because we needed it ourselves. If anything feels off or something doesn't work the way you expect, reply directly to your welcome email — it goes straight to us.
          </p>
        </div>
      </Transition>

      <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <article class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p class="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Failed events</p>
          <p class="mt-2 text-3xl font-semibold text-slate-900">{{ failedEvents }}</p>
          <p class="mt-1 text-sm text-slate-500">Webhook deliveries needing investigation</p>
        </article>

        <article class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p class="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Replay queue</p>
          <p class="mt-2 text-3xl font-semibold text-slate-900">{{ replayCandidates }}</p>
          <p class="mt-1 text-sm text-slate-500">Events that can be replayed by admins</p>
        </article>

        <article class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p class="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Active mappings</p>
          <p class="mt-2 text-3xl font-semibold text-slate-900">{{ mappings.length }}</p>
          <p class="mt-1 text-sm text-slate-500">Product-to-access rules currently configured</p>
        </article>

        <article class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p class="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Processed events</p>
          <p class="mt-2 text-3xl font-semibold text-slate-900">{{ processedToday }}</p>
          <p class="mt-1 text-sm text-slate-500">Successfully processed webhook deliveries</p>
        </article>
      </section>

      <p v-if="loading" class="text-sm text-slate-500">Loading dashboard data...</p>
      <p v-if="errorMessage" class="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
        {{ errorMessage }}
      </p>

      <section class="grid gap-4 xl:grid-cols-3">
        <article class="rounded-xl border border-slate-200 bg-white shadow-sm xl:col-span-2">
          <div class="border-b border-slate-200 px-4 py-3">
            <h2 class="text-sm font-semibold text-slate-900">Recent webhook events</h2>
            <p class="mt-1 text-xs text-slate-500">Latest delivery outcomes and processing states.</p>
          </div>
          <ul class="divide-y divide-slate-200">
            <li
              v-for="event in recentWebhookEvents"
              :key="event.id"
              class="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-sm"
            >
              <div>
                <p class="font-medium text-slate-900">#{{ event.id }} · {{ event.provider }}</p>
                <p class="text-xs text-slate-500">{{ formatDate(event.created_at) }}</p>
              </div>
              <div class="text-right">
                <p
                  class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"
                  :class="
                    event.status === 'processed'
                      ? 'bg-emerald-100 text-emerald-700'
                      : event.status === 'failed' || event.status === 'dead_letter'
                        ? 'bg-rose-100 text-rose-700'
                        : 'bg-slate-100 text-slate-700'
                  "
                >
                  {{ event.status }}
                </p>
                <p class="mt-1 text-xs text-slate-500">Attempts {{ event.attempts }}</p>
              </div>
            </li>
            <li v-if="recentWebhookEvents.length === 0" class="px-4 py-6 text-sm text-slate-500">No webhook events yet.</li>
          </ul>
        </article>

        <article class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 class="text-sm font-semibold text-slate-900">Integration health</h2>
          <p class="mt-1 text-xs text-slate-500">Current provider enablement state in this tenant.</p>

          <ul class="mt-4 space-y-3 text-sm">
            <li class="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2">
              <span class="font-medium text-slate-700">Payment provider</span>
              <span :class="paymentEnabled ? 'text-emerald-700' : 'text-slate-500'">
                {{ paymentEnabled ? 'Enabled' : 'Disabled' }}
              </span>
            </li>
            <li class="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2">
              <span class="font-medium text-slate-700">CMS provider</span>
              <span :class="cmsEnabled ? 'text-emerald-700' : 'text-slate-500'">
                {{ cmsEnabled ? 'Enabled' : 'Disabled' }}
              </span>
            </li>
            <li class="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2">
              <span class="font-medium text-slate-700">Team members</span>
              <span class="text-slate-900">{{ teamMembers.length }}</span>
            </li>
          </ul>
        </article>
      </section>

      <section class="grid gap-4 xl:grid-cols-2">
        <article class="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div class="border-b border-slate-200 px-4 py-3">
            <h2 class="text-sm font-semibold text-slate-900">Recent audit activity</h2>
          </div>
          <ul class="divide-y divide-slate-200">
            <li v-for="event in recentAuditEvents" :key="event.id" class="px-4 py-3 text-sm">
              <p class="font-medium text-slate-900">{{ event.event_type }}</p>
              <p class="text-xs text-slate-500">{{ event.target_type }} · {{ event.target_id }}</p>
              <p class="mt-1 text-xs text-slate-400">{{ formatDate(event.created_at) }}</p>
            </li>
            <li v-if="recentAuditEvents.length === 0" class="px-4 py-6 text-sm text-slate-500">No audit events yet.</li>
          </ul>
        </article>

        <article class="rounded-xl border border-slate-200 bg-white shadow-sm">
          <div class="border-b border-slate-200 px-4 py-3">
            <h2 class="text-sm font-semibold text-slate-900">Team snapshot</h2>
          </div>
          <ul class="divide-y divide-slate-200">
            <li v-for="member in teamMembers.slice(0, 6)" :key="member.id" class="flex items-center justify-between px-4 py-3 text-sm">
              <div>
                <p class="font-medium text-slate-900">{{ member.email }}</p>
                <p class="text-xs text-slate-500">{{ member.firebase_uid }}</p>
              </div>
              <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{{ member.role }}</span>
            </li>
            <li v-if="teamMembers.length === 0" class="px-4 py-6 text-sm text-slate-500">No team members found for this tenant.</li>
          </ul>
        </article>
      </section>

      <!-- Dev preview: onboarding steps -->
      <section class="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4">
        <p class="text-xs font-semibold uppercase tracking-widest text-slate-400">Onboarding preview</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <RouterLink
            :to="`/t/${session.activeTenantSlug}/onboarding?step=1`"
            class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >Step 1: Organization</RouterLink>
          <RouterLink
            :to="`/t/${session.activeTenantSlug}/onboarding?step=2`"
            class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >Step 2: Ghost</RouterLink>
          <RouterLink
            :to="`/t/${session.activeTenantSlug}/onboarding?step=3`"
            class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >Step 3: Payment provider</RouterLink>
        </div>
      </section>
    </div>
  </AppShell>
</template>

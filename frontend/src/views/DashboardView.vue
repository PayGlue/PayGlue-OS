// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { ProviderLogo, UiButton } from '../components/ui'
import {
  getDeliveryHealth,
  getIntegrationConfig,
  listMappings,
  listWebhookEvents,
} from '../lib/api'
import {
  DELIVERY_LABELS,
  DELIVERY_TONES,
  TONE_DOT,
  TONE_TAG,
  needsYouLine,
  overallHealth,
  providerCounts,
  providerHealth,
  providerLabel,
  totalCounts,
} from '../lib/deliveryHealth'
import { useSessionStore } from '../stores/session'
import type {
  DeliveryHealthSummary,
  DeliveryState,
  ProductMapping,
  WebhookEvent,
} from '../types/api'

const session = useSessionStore()

const loading = ref(false)
const errorMessage = ref<string | null>(null)

const webhookEvents = ref<WebhookEvent[]>([])
const health = ref<DeliveryHealthSummary | null>(null)
const mappings = ref<ProductMapping[]>([])

const paymentEnabled = ref(false)
const cmsEnabled = ref(false)
const providerStatus = ref<Record<string, boolean>>({})

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

    const paymentProviderKeys = ['polar', 'paypal', 'gumroad', 'paddle', 'kofi', 'creem', 'patreon', 'dodo', 'digistore24'] as const

    const [eventsResult, healthResult, mappingResult, cmsResult, ...paymentResults] =
      await Promise.allSettled([
        listWebhookEvents(tenantSlug, token),
        getDeliveryHealth(tenantSlug, token),
        listMappings(tenantSlug, token),
        getIntegrationConfig(tenantSlug, token, 'cms'),
        ...paymentProviderKeys.map((key) => getIntegrationConfig(tenantSlug, token, key)),
      ])

    if (eventsResult.status === 'fulfilled') webhookEvents.value = eventsResult.value
    if (healthResult.status === 'fulfilled') health.value = healthResult.value
    if (mappingResult.status === 'fulfilled') mappings.value = mappingResult.value
    if (cmsResult.status === 'fulfilled') cmsEnabled.value = cmsResult.value.enabled
    // Track each provider's connection state so the health panel can list them
    // individually. At least one connected provider counts as "payment enabled".
    const status: Record<string, boolean> = {}
    paymentProviderKeys.forEach((key, index) => {
      const result = paymentResults[index]
      status[key] = result?.status === 'fulfilled' && result.value.enabled
    })
    providerStatus.value = status
    paymentEnabled.value = Object.values(status).some(Boolean)

    const failedParts = [
      eventsResult,
      healthResult,
      mappingResult,
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

// PG-402: the pill, the fourth card, the health list and the activity feed
// all read the backend's delivery state, so they cannot disagree any more.
// The card counts every provider and links to the events that need you.
const counts = computed(() => totalCounts(health.value))
const needsYouCount = computed(() => counts.value.needs_you)
const retryingCount = computed(() => counts.value.retrying)
const pill = computed(() => overallHealth(health.value))
const needsYouNote = computed(() => needsYouLine(health.value?.needs_you ?? []))

// Not "today" despite the old name: this is every successful grant the events
// endpoint returned. The card says "Access delivered", which is what it is.
const deliveredCount = computed(
  () => webhookEvents.value.filter((event) => event.delivery_state === 'delivered').length,
)

const recentWebhookEvents = computed(() => webhookEvents.value.slice(0, 6))

const sourceTypeLabels: Record<string, string> = {
  button: 'Buy Button',
  paywall: 'Paywall',
  pricing_table: 'Pricing Table',
}

const sourceTypeRoutes: Record<string, string> = {
  button: 'buttons',
  paywall: 'paywall',
  pricing_table: 'pricing',
}


const providerLabels: Record<string, string> = {
  polar: 'Polar',
  lemonsqueezy: 'Lemon Squeezy',
  paypal: 'PayPal',
  gumroad: 'Gumroad',
  paddle: 'Paddle',
  kofi: 'Ko-fi',
  creem: 'Creem',
  patreon: 'Patreon',
  dodo: 'Dodo Payments',
  digistore24: 'Digistore24',
  stripe: 'Stripe',
}

// --- Headline numbers (all derived from data we already load) ------------
const connectedProviders = computed(() =>
  Object.entries(providerStatus.value)
    .filter(([, on]) => on)
    .map(([key]) => key),
)
const activeMappings = computed(() => mappings.value.filter((m) => m.is_active).length)

// Health panel: Ghost first, then every connected provider, in the same words
// as the pill and the card (PG-402).
const healthItems = computed(() =>
  connectedProviders.value.map((key) => {
    const { tone, note } = providerHealth(providerCounts(health.value, key))
    return { key, label: providerLabel(key), dot: TONE_DOT[tone], note }
  }),
)

// Publication name for the activity feed -- one tenant is one Ghost
// publication, so the title-cased slug reads better than a generic "Ghost"
// (e.g. "Access synced to Demo"), especially for creators with several.
const publicationName = computed(() => {
  const slug = session.activeTenantSlug ?? ''
  if (!slug) return 'your publication'
  return slug
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
})

// Anonymised activity feed -- verb from the delivery state + provider + time,
// never any end-customer email or name. A delivery PayGlue still retries is
// told apart from one nobody will retry (PG-402).
const verbFor = (state: DeliveryState): string => {
  const to = publicationName.value
  switch (state) {
    case 'delivered': return `Access synced to ${to}`
    case 'retrying': return `Retrying delivery to ${to}`
    case 'needs_you': return `Not delivered to ${to}`
    case 'skipped': return 'Event skipped'
    case 'scheduled': return 'Access ends at the end of the paid period'
    case 'rejected': return 'Delivery rejected, signature did not match'
    case 'test': return `Test purchase not delivered to ${to}`
    default: return 'Processing'
  }
}
const stateTag = (state: DeliveryState) => {
  const tone = DELIVERY_TONES[state]
  return { label: DELIVERY_LABELS[state], cls: TONE_TAG[tone] }
}
const PILL_CLASSES = {
  good: 'border-slate-200 bg-white text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200',
  warn: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300',
  bad: 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300',
  neutral: 'border-slate-200 bg-white text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200',
} as const
const relativeTime = (value: string) => {
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return ''
  const diff = Math.max(0, Date.now() - then)
  const m = Math.round(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h`
  return `${Math.round(h / 24)}d`
}
const activityItems = computed(() =>
  recentWebhookEvents.value.map((event) => ({
    id: event.id,
    provider: event.provider,
    providerLabel: providerLabel(event.provider),
    verb: verbFor(event.delivery_state),
    tag: stateTag(event.delivery_state),
    time: relativeTime(event.created_at),
  })),
)

// Sparkline: processed events per day over the last 30 days, rendered as an
// SVG area path. Empty when there is nothing yet.
const CHART_W = 720
const CHART_H = 150
const unlockSeries = computed(() => {
  const days = 30
  const buckets = new Array(days).fill(0)
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - (days - 1)).getTime()
  for (const event of webhookEvents.value) {
    if (event.delivery_state !== 'delivered') continue
    const t = new Date(event.created_at).getTime()
    if (Number.isNaN(t) || t < start) continue
    const idx = Math.min(days - 1, Math.floor((t - start) / 86400000))
    if (idx >= 0) buckets[idx] += 1
  }
  return buckets
})
const totalUnlocks = computed(() => unlockSeries.value.reduce((a, b) => a + b, 0))
const chartPaths = computed(() => {
  const data = unlockSeries.value
  const n = data.length
  const pad = 6
  const max = Math.max(1, ...data) * 1.15
  const x = (i: number) => pad + (CHART_W - pad * 2) * (i / (n - 1))
  const y = (v: number) => CHART_H - pad - (CHART_H - pad * 2) * (v / max)
  let line = `M${x(0)} ${y(data[0])}`
  for (let i = 1; i < n; i++) {
    const xc = (x(i - 1) + x(i)) / 2
    const ym = (y(data[i - 1]) + y(data[i])) / 2
    line += ` Q ${x(i - 1)} ${y(data[i - 1])} ${xc} ${ym} Q ${xc} ${ym} ${x(i)} ${y(data[i])}`
  }
  const area = `${line} L ${x(n - 1)} ${CHART_H - pad} L ${x(0)} ${CHART_H - pad} Z`
  return { line, area, endX: x(n - 1), endY: y(data[n - 1]) }
})

// One row per widget that sells a mapped product, named after the widget
// ("Founding Member", Buy Button). used_in comes from the widgets themselves;
// source_name was whatever the last editor wrote and read "Demo" four times.
const featureConnections = computed(() => {
  const rows: { id: string; name: string; typeLabel: string; providerLabel: string; route: string | null }[] = []
  for (const m of mappings.value.filter((mapping) => mapping.is_active)) {
    const providerName = providerLabels[m.payment_provider] ?? m.payment_provider
    const offers = m.used_in ?? []
    if (offers.length === 0) {
      rows.push({
        id: `${m.id}`,
        name: m.metadata?.source_name || m.external_product_id,
        typeLabel: sourceTypeLabels[m.metadata?.source_type ?? ''] ?? 'Mapping',
        providerLabel: providerName,
        route: m.metadata?.source_type
          ? `/t/${session.activeTenantSlug}/${sourceTypeRoutes[m.metadata.source_type]}`
          : null,
      })
      continue
    }
    offers.forEach((offer, index) => {
      const [type, ...rest] = offer.split(': ')
      const typeKey = Object.keys(sourceTypeLabels).find((key) => sourceTypeLabels[key] === type)
      rows.push({
        id: `${m.id}-${index}`,
        name: rest.join(': ') || offer,
        typeLabel: type || 'Mapping',
        providerLabel: providerName,
        route: typeKey ? `/t/${session.activeTenantSlug}/${sourceTypeRoutes[typeKey]}` : null,
      })
    })
  }
  return rows
})

// The one next step for this publication, in the order the work happens:
// Ghost, a provider, a product mapped, a first purchase seen. Replaces the
// audit log and team list the home page used to end with (PG-402).
const nextStep = computed(() => {
  const slug = session.activeTenantSlug
  if (!cmsEnabled.value) {
    return { text: 'Connect your Ghost site, so PayGlue can grant access there.', action: 'Connect Ghost', to: `/t/${slug}/connection/ghost` }
  }
  if (!paymentEnabled.value) {
    return { text: 'Connect the payment provider you sell through.', action: 'Connect a provider', to: `/t/${slug}/connections` }
  }
  if (activeMappings.value === 0) {
    return { text: 'Map a product to Ghost access, so a purchase knows what to unlock.', action: 'Map a product', to: `/t/${slug}/mappings` }
  }
  if (deliveredCount.value === 0) {
    const provider = providerLabels[connectedProviders.value[0] ?? ''] ?? 'your provider'
    return { text: `Send a test purchase through ${provider} to see a reader appear in Ghost.`, action: 'Send test', to: `/t/${slug}/mappings` }
  }
  return { text: 'Setup is complete. Every new purchase shows up in Events.', action: 'View events', to: `/t/${slug}/events`, done: true }
})

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
    <div class="space-y-5">

      <!-- Health status (page title/subtitle come from AppShell). Static dot:
           a pulsing one made "healthy" the loudest thing on the page. -->
      <div class="flex justify-end">
        <span
          class="inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm font-semibold shadow-sm"
          :class="PILL_CLASSES[pill.tone]"
          role="status"
        >
          <span class="h-2.5 w-2.5 rounded-full" :class="TONE_DOT[pill.tone]"></span>
          {{ pill.text }}
        </span>
      </div>

      <!-- Thank You banner (einmalig nach erstem Onboarding) -->
      <Transition
        enter-active-class="transition-all duration-500 ease-out"
        enter-from-class="opacity-0 -translate-y-2"
        leave-active-class="transition-all duration-300 ease-in"
        leave-to-class="opacity-0 -translate-y-2"
      >
        <div
          v-if="showThankYou"
          class="relative rounded-2xl border border-indigo-100 dark:border-indigo-500/30 bg-gradient-to-br from-indigo-50 to-white p-5 shadow-sm dark:border-indigo-500/20 dark:from-indigo-500/10 dark:to-slate-900"
        >
          <button
            class="absolute right-4 top-4 text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:text-slate-300"
            aria-label="Dismiss"
            @click="dismissThankYou"
          >
            <svg class="h-4 w-4" viewBox="0 0 16 16" fill="none"><path d="M3 3l10 10M13 3L3 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </button>
          <p class="mb-1 text-base font-semibold text-slate-900 dark:text-slate-100">You're in. Thank you for being one of the first.</p>
          <p class="max-w-xl text-sm text-slate-600 dark:text-slate-300">
            We built PayGlue because we needed it ourselves. If anything feels off or something doesn't work the way you expect, reply directly to your welcome email, it goes straight to us.
          </p>
        </div>
      </Transition>

      <!-- Two columns from phone width up. On a phone each card drops its icon
           row and its note and the number shrinks, so the four fit one screen
           (PG-402). Done on the grid, so every card follows. -->
      <section class="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4 max-sm:[&>*]:p-3 max-sm:[&>*>div:first-child]:hidden max-sm:[&>*>p:last-child]:hidden max-sm:[&>*>p:first-of-type]:text-2xl">
        <!-- Access delivered -->
        <article class="group rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 p-4 shadow-sm transition-transform hover:-translate-y-0.5">
          <div class="mb-4 flex items-start justify-between">
            <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 dark:bg-indigo-500/15 dark:text-indigo-300">
              <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none"><path d="m5 13 4 4L19 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>
          </div>
          <p class="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100 tabular-nums">{{ deliveredCount }}</p>
          <p class="mt-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">Access delivered</p>
          <p class="mt-0.5 text-xs text-slate-400 dark:text-slate-500">Successful Ghost grants</p>
        </article>

        <!-- Connected providers -->
        <article class="group rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 p-4 shadow-sm transition-transform hover:-translate-y-0.5">
          <div class="mb-4 flex items-start justify-between">
            <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-50 dark:bg-sky-500/10 text-sky-600 dark:bg-sky-500/15 dark:text-sky-300">
              <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none"><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>
          </div>
          <p class="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100 tabular-nums">{{ connectedProviders.length }}</p>
          <p class="mt-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">Connected providers</p>
          <p class="mt-0.5 text-xs text-slate-400 dark:text-slate-500">Payment sources live</p>
        </article>

        <!-- Access rules -->
        <article class="group rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 p-4 shadow-sm transition-transform hover:-translate-y-0.5">
          <div class="mb-4 flex items-start justify-between">
            <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-50 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300">
              <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none"><rect x="4" y="3" width="16" height="18" rx="2.5" stroke="currentColor" stroke-width="1.8"/><path d="M9 8h6M9 12h6M9 16h3" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>
            </span>
            <span class="rounded-full bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-[11px] font-semibold text-slate-500 dark:text-slate-400">Live</span>
          </div>
          <p class="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100 tabular-nums">{{ activeMappings }}</p>
          <p class="mt-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">Access rules</p>
          <p class="mt-0.5 text-xs text-slate-400 dark:text-slate-500">Products wired to Ghost</p>
        </article>

        <!-- Needs you: every provider, one number, and the list behind it -->
        <RouterLink
          :to="{ path: `/t/${session.activeTenantSlug}/events`, query: { state: 'needs_you' } }"
          class="group rounded-2xl border bg-white p-4 shadow-sm transition-transform hover:-translate-y-0.5 dark:bg-slate-900"
          :class="needsYouCount > 0 ? 'border-rose-200 dark:border-rose-500/40' : 'border-slate-200 dark:border-slate-800'"
        >
          <div class="mb-4 flex items-start justify-between">
            <span
              class="flex h-10 w-10 items-center justify-center rounded-xl"
              :class="needsYouCount > 0 ? 'bg-rose-50 text-rose-600 dark:bg-rose-500/15 dark:text-rose-300' : 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300'"
            >
              <svg v-if="needsYouCount === 0" class="h-5 w-5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M9 12l2 2 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8"/></svg>
              <svg v-else class="h-5 w-5" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 9v4m0 4h.01M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>
            <span v-if="needsYouCount > 0" class="rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-semibold text-rose-700 dark:bg-rose-500/15 dark:text-rose-300">Review</span>
          </div>
          <p class="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100 tabular-nums">{{ needsYouCount }}</p>
          <p class="mt-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
            {{ needsYouCount === 0 ? (retryingCount > 0 ? 'Nothing needs you yet' : 'Every purchase reached Ghost') : needsYouCount === 1 ? 'Delivery needs you' : 'Deliveries need you' }}
          </p>
          <p class="mt-0.5 text-xs" :class="needsYouCount > 0 ? 'text-rose-700 dark:text-rose-300' : retryingCount > 0 ? 'text-amber-700 dark:text-amber-300' : 'text-slate-500 dark:text-slate-400'">
            {{ needsYouCount > 0 ? needsYouNote : retryingCount > 0 ? `${retryingCount} retrying, PayGlue tries again` : 'Nothing to retry' }}
          </p>
        </RouterLink>
      </section>

      <p v-if="loading" class="text-sm text-slate-500 dark:text-slate-400">Loading dashboard data...</p>
      <p v-if="errorMessage" class="rounded-2xl border border-amber-300 bg-amber-50 dark:bg-amber-500/10 px-4 py-2.5 text-sm text-amber-800 dark:text-amber-300">
        {{ errorMessage }}
      </p>

      <!-- Next step: one sentence, one action, changing with the setup. -->
      <section
        class="flex flex-col gap-3 rounded-2xl border p-4 sm:flex-row sm:items-center sm:gap-4"
        :class="nextStep.done ? 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900' : 'border-indigo-100 bg-indigo-50/60 dark:border-indigo-500/30 dark:bg-indigo-500/10'"
        aria-labelledby="next-step-title"
      >
        <span class="hidden h-9 w-9 shrink-0 sm:flex items-center justify-center rounded-xl bg-white text-indigo-600 shadow-sm dark:bg-slate-900 dark:text-indigo-300" aria-hidden="true">
          <svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none"><path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </span>
        <div class="min-w-0 flex-1">
          <h2 id="next-step-title" class="text-sm font-semibold text-slate-900 dark:text-slate-100">Next step</h2>
          <p class="mt-0.5 text-sm text-slate-700 dark:text-slate-300">{{ nextStep.text }}</p>
        </div>
        <UiButton :variant="nextStep.done ? 'default' : 'primary'" size="sm" :to="nextStep.to" class="shrink-0 self-start sm:self-auto">{{ nextStep.action }}</UiButton>
      </section>

      <!-- Chart + connection health -->
      <section class="grid gap-4 xl:grid-cols-3">
        <article class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 shadow-sm xl:col-span-2">
          <div class="flex items-start justify-between gap-3 px-5 pt-4">
            <div>
              <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">Access unlocked</h2>
              <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Successful Ghost grants, last 30 days</p>
            </div>
            <div class="text-right">
              <p class="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100 tabular-nums">{{ totalUnlocks }}</p>
              <p class="text-[11px] text-slate-400 dark:text-slate-500">total unlocks</p>
            </div>
          </div>
          <div class="px-3 pb-2 pt-3">
            <svg :viewBox="`0 0 ${CHART_W} ${CHART_H}`" preserveAspectRatio="none" class="h-40 w-full">
              <defs>
                <linearGradient id="pgArea" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stop-color="#4f46e5" stop-opacity="0.22" />
                  <stop offset="1" stop-color="#4f46e5" stop-opacity="0" />
                </linearGradient>
              </defs>
              <path :d="chartPaths.area" fill="url(#pgArea)" />
              <path :d="chartPaths.line" fill="none" stroke="#4f46e5" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
              <circle :cx="chartPaths.endX" :cy="chartPaths.endY" r="4" fill="#4f46e5" stroke="#fff" stroke-width="2" />
            </svg>
          </div>
        </article>

        <article class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 shadow-sm">
          <div class="flex items-center justify-between px-5 pt-4">
            <div>
              <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">Connection health</h2>
              <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Live delivery status</p>
            </div>
            <RouterLink :to="`/t/${session.activeTenantSlug}/connection/ghost`" class="text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline">Manage</RouterLink>
          </div>
          <div class="mt-2">
            <div class="flex items-center gap-3 px-5 py-2.5">
              <ProviderLogo provider="ghost" size="sm" />
              <span class="flex-1 text-sm font-semibold text-slate-800 dark:text-slate-100">Ghost CMS</span>
              <span class="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                <span class="h-1.5 w-1.5 rounded-full" :class="cmsEnabled ? 'bg-emerald-500' : 'bg-slate-300'"></span>
                {{ cmsEnabled ? 'Delivering' : 'Not connected' }}
              </span>
            </div>
            <div v-for="h in healthItems" :key="h.key" class="flex items-center gap-3 border-t border-slate-100 dark:border-slate-800 px-5 py-2.5">
              <ProviderLogo :provider="h.key" size="sm" />
              <span class="flex-1 text-sm font-semibold text-slate-800 dark:text-slate-100">{{ h.label }}</span>
              <span class="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                <span class="h-1.5 w-1.5 rounded-full" :class="h.dot"></span>
                {{ h.note }}
              </span>
            </div>
            <p v-if="healthItems.length === 0" class="px-5 py-4 text-sm text-slate-400 dark:text-slate-500">No payment provider connected yet.</p>
          </div>
        </article>
      </section>

      <section class="grid gap-4 xl:grid-cols-2 [&>*]:min-w-0">
        <!-- Recent activity (anonymised: no end-customer email or name) -->
        <article class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 shadow-sm">
          <div class="flex items-center justify-between px-5 pt-4">
            <div>
              <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">Recent activity</h2>
              <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">What PayGlue just did for your members</p>
            </div>
            <RouterLink :to="`/t/${session.activeTenantSlug}/events`" class="text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline">View events</RouterLink>
          </div>
          <div class="mt-2 pb-1">
            <div v-for="a in activityItems" :key="a.id" class="flex items-center gap-3 px-5 py-2.5">
              <ProviderLogo :provider="a.provider" size="md" />
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm text-slate-800 dark:text-slate-100">{{ a.verb }}</p>
                <p class="truncate text-xs text-slate-500 dark:text-slate-400">via {{ a.providerLabel }}</p>
              </div>
              <span class="shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold" :class="a.tag.cls">{{ a.tag.label }}</span>
              <span class="w-9 shrink-0 text-right text-[11px] text-slate-400 dark:text-slate-500">{{ a.time }}</span>
            </div>
            <p v-if="activityItems.length === 0" class="px-5 py-6 text-sm text-slate-400 dark:text-slate-500">No activity yet. Once a purchase comes in, you'll see it here.</p>
          </div>
        </article>

        <!-- Feature connections -->
        <article class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 shadow-sm">
          <div class="px-5 pt-4">
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">Feature connections</h2>
            <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Which feature is wired to which provider</p>
          </div>
          <div class="mt-2 pb-1">
            <template v-for="fc in featureConnections" :key="fc.id">
              <RouterLink v-if="fc.route" :to="fc.route" class="flex items-center gap-3 px-5 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800/60">
                <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-sm font-bold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300" aria-hidden="true">{{ fc.name.charAt(0).toUpperCase() }}</span>
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{{ fc.name }}</p>
                  <p class="truncate text-xs text-slate-500 dark:text-slate-400">{{ fc.typeLabel }}</p>
                </div>
                <span class="shrink-0 rounded-full bg-indigo-50 dark:bg-indigo-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-indigo-600 dark:text-indigo-400">{{ fc.providerLabel }}</span>
              </RouterLink>
              <div v-else class="flex items-center gap-3 px-5 py-2.5">
                <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-sm font-bold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300" aria-hidden="true">{{ fc.name.charAt(0).toUpperCase() }}</span>
                <div class="min-w-0 flex-1">
                  <p class="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{{ fc.name }}</p>
                  <p class="truncate text-xs text-slate-500 dark:text-slate-400">{{ fc.typeLabel }}</p>
                </div>
                <span class="shrink-0 rounded-full bg-indigo-50 dark:bg-indigo-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-indigo-600 dark:text-indigo-400">{{ fc.providerLabel }}</span>
              </div>
            </template>
            <p v-if="featureConnections.length === 0" class="px-5 py-6 text-sm text-slate-400 dark:text-slate-500">
              No features linked to a provider yet. Start with a
              <RouterLink :to="`/t/${session.activeTenantSlug}/buttons`" class="font-semibold text-indigo-600 dark:text-indigo-400 hover:underline">Buy Button</RouterLink>.
            </p>
          </div>
        </article>
      </section>

      <!-- Quick actions -->
      <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <RouterLink :to="`/t/${session.activeTenantSlug}/connections`" class="group flex items-center gap-3 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 p-4 shadow-sm transition-transform hover:-translate-y-0.5">
          <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 dark:bg-indigo-500/15 dark:text-indigo-300"><svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></span>
          <span class="flex-1"><span class="block text-sm font-semibold text-slate-800 dark:text-slate-100">Add a connection</span><span class="block text-xs text-slate-400 dark:text-slate-500">Wire a new provider</span></span>
        </RouterLink>
        <RouterLink :to="`/t/${session.activeTenantSlug}/buttons`" class="group flex items-center gap-3 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 p-4 shadow-sm transition-transform hover:-translate-y-0.5">
          <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 dark:bg-indigo-500/15 dark:text-indigo-300"><svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none"><rect x="3" y="6" width="18" height="12" rx="3" stroke="currentColor" stroke-width="1.9"/><path d="M7 12h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></span>
          <span class="flex-1"><span class="block text-sm font-semibold text-slate-800 dark:text-slate-100">Create a buy button</span><span class="block text-xs text-slate-400 dark:text-slate-500">Sell in one click</span></span>
        </RouterLink>
        <RouterLink :to="`/t/${session.activeTenantSlug}/mappings`" class="group flex items-center gap-3 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 p-4 shadow-sm transition-transform hover:-translate-y-0.5">
          <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 dark:bg-indigo-500/15 dark:text-indigo-300"><svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none"><path d="M5 12l4 4L19 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
          <span class="flex-1"><span class="block text-sm font-semibold text-slate-800 dark:text-slate-100">Test a connection</span><span class="block text-xs text-slate-400 dark:text-slate-500">Verify without a sale</span></span>
        </RouterLink>
        <RouterLink :to="`/t/${session.activeTenantSlug}/events`" class="group flex items-center gap-3 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-800 dark:bg-slate-900 p-4 shadow-sm transition-transform hover:-translate-y-0.5">
          <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 dark:bg-indigo-500/15 dark:text-indigo-300"><svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none"><path d="M4 5h16M4 12h16M4 19h10" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg></span>
          <span class="flex-1"><span class="block text-sm font-semibold text-slate-800 dark:text-slate-100">View all events</span><span class="block text-xs text-slate-400 dark:text-slate-500">Full delivery log</span></span>
        </RouterLink>
      </section>
    </div>
  </AppShell>
</template>

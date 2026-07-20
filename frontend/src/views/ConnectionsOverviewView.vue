// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { PageHeader, StatusPill, ProviderLogo } from '../components/ui'
import { getGhostStripeStatus, getIntegrationConfig, listMappings, listWebhookEvents } from '../lib/api'
import { CONNECTION_PROVIDERS, PROVIDER_ORDER, type ProviderKey } from '../lib/connectionProviders'
import { useSessionStore } from '../stores/session'
import type { ProductMapping, WebhookEvent } from '../types/api'

const session = useSessionStore()
const router = useRouter()

const loading = ref(false)
const cmsEnabled = ref(false)
const enabled = ref<Record<string, boolean>>({})
const mappings = ref<ProductMapping[]>([])
const events = ref<WebhookEvent[]>([])
const stripeConnected = ref<boolean | null>(null)

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) throw new Error('Missing tenant context.')
  return { tenantSlug: session.activeTenantSlug, token: session.idToken }
}

const load = async () => {
  loading.value = true
  try {
    const { tenantSlug, token } = context()
    const [cmsRes, mapRes, evRes, ...provRes] = await Promise.allSettled([
      getIntegrationConfig(tenantSlug, token, 'cms'),
      listMappings(tenantSlug, token),
      listWebhookEvents(tenantSlug, token),
      ...PROVIDER_ORDER.map((key) => getIntegrationConfig(tenantSlug, token, key)),
    ])
    if (cmsRes.status === 'fulfilled') cmsEnabled.value = cmsRes.value.enabled
    if (mapRes.status === 'fulfilled') mappings.value = mapRes.value
    if (evRes.status === 'fulfilled') events.value = evRes.value
    const on: Record<string, boolean> = {}
    PROVIDER_ORDER.forEach((key, i) => {
      const r = provRes[i]
      on[key] = r?.status === 'fulfilled' && r.value.enabled
    })
    enabled.value = on
    // Stripe status only matters once Ghost is connected.
    if (cmsEnabled.value) {
      try {
        const s = await getGhostStripeStatus(tenantSlug, token)
        stripeConnected.value = s.connected
      } catch { /* leave null */ }
    }
  } finally {
    loading.value = false
  }
}

const failuresByProvider = computed(() => {
  const counts: Record<string, number> = {}
  for (const e of events.value) {
    if (e.status === 'failed' || e.status === 'dead_letter') counts[e.provider] = (counts[e.provider] ?? 0) + 1
  }
  return counts
})

const mappingsByProvider = computed(() => {
  const counts: Record<string, number> = {}
  for (const m of mappings.value) {
    if (m.is_active) counts[m.payment_provider] = (counts[m.payment_provider] ?? 0) + 1
  }
  return counts
})

interface Card {
  key: ProviderKey
  name: string
  state: 'connected' | 'attention' | 'off'
  sub: string
}

const cards = computed<Card[]>(() =>
  PROVIDER_ORDER.map((key) => {
    const on = enabled.value[key]
    const fails = failuresByProvider.value[key] ?? 0
    const maps = mappingsByProvider.value[key] ?? 0
    let state: Card['state'] = 'off'
    let sub = 'Not set up yet'
    if (on) {
      if (fails > 0) {
        state = 'attention'
        sub = `${maps} mapping${maps === 1 ? '' : 's'} · ${fails} to retry`
      } else {
        state = 'connected'
        sub = maps > 0 ? `${maps} active mapping${maps === 1 ? '' : 's'}` : 'Connected'
      }
    }
    return { key, name: CONNECTION_PROVIDERS[key].name, state, sub }
  }),
)

const goDetail = (key: string) => router.push(`/t/${session.activeTenantSlug}/connection/${key}`)
const stateTone = (s: Card['state']) => (s === 'connected' ? 'good' : s === 'attention' ? 'warn' : 'neutral')
const stateLabel = (s: Card['state']) => (s === 'connected' ? 'Connected' : s === 'attention' ? 'Needs attention' : 'Not connected')

onMounted(load)
</script>

<template>
  <AppShell>
    <div class="space-y-6">
      <PageHeader title="Connections" description="Connect Ghost and your payment providers. Access syncs automatically." />

      <p v-if="loading" class="px-1 text-sm text-slate-500 dark:text-slate-400">Loading connections...</p>

      <!-- Content destination: Ghost + Stripe status -->
      <div>
        <p class="mb-3 text-[11px] font-bold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">Content</p>
        <div class="grid gap-4 sm:grid-cols-2">
          <button
            type="button"
            class="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-transform hover:-translate-y-0.5 dark:border-slate-800 dark:bg-slate-900"
            @click="router.push(`/t/${session.activeTenantSlug}/connection/ghost`)"
          >
            <div class="flex items-center gap-3">
              <ProviderLogo provider="ghost" />
              <div class="min-w-0">
                <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Ghost CMS</p>
                <p class="mt-0.5 text-xs text-slate-400 dark:text-slate-500">Where access is granted</p>
              </div>
            </div>
            <div class="flex items-center justify-between border-t border-slate-100 pt-3 dark:border-slate-800">
              <StatusPill :tone="cmsEnabled ? 'good' : 'neutral'" dot>{{ cmsEnabled ? 'Delivering' : 'Not connected' }}</StatusPill>
              <span class="text-xs font-semibold text-indigo-600 dark:text-indigo-400">Open →</span>
            </div>
          </button>

          <button
            type="button"
            class="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-transform hover:-translate-y-0.5 dark:border-slate-800 dark:bg-slate-900"
            @click="router.push(`/t/${session.activeTenantSlug}/connection/stripe`)"
          >
            <div class="flex items-center gap-3">
              <ProviderLogo provider="stripe" />
              <div class="min-w-0">
                <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Stripe</p>
                <p class="mt-0.5 text-xs text-slate-400 dark:text-slate-500">Managed inside Ghost</p>
              </div>
            </div>
            <div class="flex items-center justify-between border-t border-slate-100 pt-3 dark:border-slate-800">
              <StatusPill :tone="stripeConnected === true ? 'good' : stripeConnected === false ? 'warn' : 'neutral'" dot>
                {{ stripeConnected === true ? 'Connected in Ghost' : stripeConnected === false ? 'Not in Ghost' : 'Disabled' }}
              </StatusPill>
              <span class="text-xs font-semibold text-indigo-600 dark:text-indigo-400">Open →</span>
            </div>
          </button>
        </div>
      </div>

      <!-- Payment providers grid -->
      <div>
        <p class="mb-3 text-[11px] font-bold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">Payment providers</p>
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <button
            v-for="c in cards"
            :key="c.key"
            type="button"
            class="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-transform hover:-translate-y-0.5 dark:border-slate-800 dark:bg-slate-900"
            @click="goDetail(c.key)"
          >
            <div class="flex items-center gap-3">
              <ProviderLogo :provider="c.key" />
              <div class="min-w-0">
                <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ c.name }}</p>
                <p class="mt-0.5 truncate text-xs text-slate-400 dark:text-slate-500">{{ c.sub }}</p>
              </div>
            </div>
            <div class="flex items-center justify-between border-t border-slate-100 pt-3 dark:border-slate-800">
              <StatusPill :tone="stateTone(c.state)" dot>{{ stateLabel(c.state) }}</StatusPill>
              <span class="text-xs font-semibold text-indigo-600 dark:text-indigo-400">{{ c.state === 'off' ? 'Connect' : 'Open' }} →</span>
            </div>
          </button>
        </div>
      </div>
    </div>
  </AppShell>
</template>

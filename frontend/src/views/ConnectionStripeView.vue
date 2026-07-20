// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { PageHeader, UiCard, UiButton, ProviderLogo } from '../components/ui'
import { ApiHttpError, getGhostStripeStatus, getIntegrationConfig } from '../lib/api'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()
const ghostConnected = ref(false)
const stripeStatus = ref<{ connected: boolean; display_name?: string | null } | null>(null)
const loading = ref(true)

const load = async () => {
  loading.value = true
  try {
    if (!session.activeTenantSlug || !session.idToken) return
    const { tenantSlug, idToken } = { tenantSlug: session.activeTenantSlug, idToken: session.idToken }
    const config = await getIntegrationConfig(tenantSlug, idToken, 'cms').catch(() => null)
    if (config?.enabled) {
      ghostConnected.value = true
      stripeStatus.value = await getGhostStripeStatus(tenantSlug, idToken).catch(() => ({ connected: false }))
    }
  } catch (e) {
    if (!(e instanceof ApiHttpError && e.status === 404)) {
      // ignore
    }
  } finally {
    loading.value = false
  }
}

const steps = [
  { title: 'Open Ghost Admin', body: 'Go to your Ghost Admin panel and navigate to <strong>Settings</strong> and then <strong>Membership</strong>.' },
  { title: 'Click "Connect with Stripe"', body: 'Ghost walks you through a short OAuth flow with Stripe. No API keys needed. This only takes a minute.' },
  { title: 'Come back here', body: 'Once connected in Ghost, reload this page. PayGlue detects the connection automatically and will start granting complimentary paid memberships on purchase.' },
]

onMounted(load)
</script>

<template>
  <AppShell>
    <div class="space-y-5">
      <PageHeader
        title="Stripe"
        description="PayGlue does not connect to Stripe directly. Stripe is connected inside your Ghost blog and enables native paid member access (comped memberships)."
      >
        <template #actions>
          <ProviderLogo provider="stripe" size="md" />
        </template>
      </PageHeader>

      <!-- Ghost not connected yet -->
      <div v-if="!loading && !ghostConnected" class="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm dark:border-amber-500/30 dark:bg-amber-500/10">
        <p class="text-sm font-medium text-amber-800 dark:text-amber-300">Ghost CMS not connected yet</p>
        <p class="mt-1 text-xs text-amber-700 dark:text-amber-400">Connect your Ghost blog first. PayGlue will then check automatically whether Stripe is set up in Ghost.</p>
        <UiButton class="mt-3" variant="primary" :to="`/t/${session.activeTenantSlug}/connection/ghost`">Connect Ghost CMS</UiButton>
      </div>

      <!-- Live status from Ghost -->
      <UiCard v-if="!loading && ghostConnected && stripeStatus" title="Live status from your Ghost blog">
        <div
          v-if="stripeStatus.connected"
          class="flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 dark:border-emerald-500/30 dark:bg-emerald-500/10"
        >
          <span class="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-500"></span>
          <div>
            <p class="text-sm font-medium text-emerald-800 dark:text-emerald-300">Stripe is connected in Ghost</p>
            <p v-if="stripeStatus.display_name" class="mt-0.5 text-xs text-emerald-700 dark:text-emerald-400">Account: {{ stripeStatus.display_name }}</p>
            <p class="mt-0.5 text-xs text-emerald-700 dark:text-emerald-400">Customers who buy through PayGlue receive a complimentary paid membership in Ghost. Native content gating works.</p>
          </div>
        </div>

        <div v-else class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10">
          <div class="flex items-start gap-3">
            <span class="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-amber-400"></span>
            <div>
              <p class="text-sm font-medium text-amber-800 dark:text-amber-300">No Stripe connection found in Ghost</p>
              <p class="mt-0.5 text-xs text-amber-700 dark:text-amber-400">Customers will be added as free members with a PayGlue label. Use the PayGlue JS Paywall snippet for content gating.</p>
            </div>
          </div>
          <RouterLink :to="`/t/${session.activeTenantSlug}/connection/ghost`" class="mt-3 inline-block text-xs font-semibold text-indigo-600 hover:underline dark:text-indigo-400">
            View Stripe status in Ghost CMS settings
          </RouterLink>
        </div>
      </UiCard>

      <!-- How-to -->
      <UiCard title="How to connect Stripe in Ghost" description="Stripe is managed directly inside Ghost. You do not need to enter any Stripe API keys in PayGlue.">
        <div class="space-y-2.5">
          <div
            v-for="(step, i) in steps"
            :key="i"
            class="rounded-xl border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/40"
          >
            <div class="flex items-start gap-2.5">
              <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[11px] font-bold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">{{ i + 1 }}</span>
              <div class="min-w-0">
                <p class="text-sm font-semibold text-slate-800 dark:text-slate-100">{{ step.title }}</p>
                <!-- eslint-disable-next-line vue/no-v-html -->
                <p class="mt-0.5 text-xs leading-relaxed text-slate-500 dark:text-slate-400" v-html="step.body"></p>
              </div>
            </div>
          </div>
        </div>

        <div class="mt-4 rounded-xl border border-sky-100 bg-sky-50 p-3 dark:border-sky-500/30 dark:bg-sky-500/10">
          <p class="text-xs font-medium text-sky-800 dark:text-sky-300">Stripe not available in your country?</p>
          <p class="mt-0.5 text-xs text-sky-700 dark:text-sky-400">No problem. Use a different payment provider such as Polar to accept payments without Stripe. Customers are added as free members with a label, and the PayGlue JS Paywall snippet handles content access.</p>
        </div>
      </UiCard>
    </div>
  </AppShell>
</template>

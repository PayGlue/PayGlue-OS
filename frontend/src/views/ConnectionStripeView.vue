// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
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

onMounted(load)
</script>

<template>
  <AppShell>
    <div class="space-y-4">
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h1 class="text-lg font-semibold text-slate-900">Stripe</h1>
        <p class="mt-0.5 text-sm text-slate-500">
          PayGlue does not connect to Stripe directly. Stripe is connected inside your Ghost blog
          and enables native paid member access (comped memberships).
        </p>
      </section>

      <!-- Ghost not connected yet -->
      <section v-if="!loading && !ghostConnected" class="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
        <p class="text-sm font-medium text-amber-800">Ghost CMS not connected yet</p>
        <p class="mt-1 text-xs text-amber-700">
          Connect your Ghost blog first. PayGlue will then check automatically whether Stripe is set up in Ghost.
        </p>
        <RouterLink
          :to="`/t/${session.activeTenantSlug}/connection/ghost`"
          class="mt-3 inline-block rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
        >
          Connect Ghost CMS
        </RouterLink>
      </section>

      <!-- Live status from Ghost -->
      <section v-if="!loading && ghostConnected && stripeStatus" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <p class="mb-3 text-xs font-semibold uppercase tracking-widest text-indigo-600">Live status from your Ghost blog</p>

        <div v-if="stripeStatus.connected" class="flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3">
          <span class="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-500"></span>
          <div>
            <p class="text-sm font-medium text-emerald-800">Stripe is connected in Ghost</p>
            <p v-if="stripeStatus.display_name" class="mt-0.5 text-xs text-emerald-700">Account: {{ stripeStatus.display_name }}</p>
            <p class="mt-0.5 text-xs text-emerald-700">
              Customers who buy through PayGlue receive a complimentary paid membership in Ghost.
              Native content gating works.
            </p>
          </div>
        </div>

        <div v-else class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <div class="flex items-start gap-3">
            <span class="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-amber-400"></span>
            <div>
              <p class="text-sm font-medium text-amber-800">No Stripe connection found in Ghost</p>
              <p class="mt-0.5 text-xs text-amber-700">
                Customers will be added as free members with a PayGlue label. Use the
                PayGlue JS Paywall snippet for content gating.
              </p>
            </div>
          </div>
          <RouterLink
            :to="`/t/${session.activeTenantSlug}/connection/ghost`"
            class="mt-3 inline-block text-xs text-indigo-600 hover:underline"
          >
            View Stripe status in Ghost CMS settings
          </RouterLink>
        </div>
      </section>

      <!-- How-to -->
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <p class="mb-3 text-xs font-semibold uppercase tracking-widest text-indigo-600">How to connect Stripe in Ghost</p>
        <p class="mb-4 text-xs text-slate-500">
          Stripe is managed directly inside Ghost. You do not need to enter any Stripe API keys in PayGlue.
        </p>
        <div class="space-y-2">
          <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 1</p>
            <p class="mt-0.5 text-sm font-medium text-slate-800">Open Ghost Admin</p>
            <p class="mt-0.5 text-xs text-slate-500">
              Go to your Ghost Admin panel and navigate to
              <strong>Settings</strong> and then <strong>Membership</strong>.
            </p>
          </div>
          <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 2</p>
            <p class="mt-0.5 text-sm font-medium text-slate-800">Click "Connect with Stripe"</p>
            <p class="mt-0.5 text-xs text-slate-500">
              Ghost walks you through a short OAuth flow with Stripe. No API keys needed.
              This only takes a minute.
            </p>
          </div>
          <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 3</p>
            <p class="mt-0.5 text-sm font-medium text-slate-800">Come back here</p>
            <p class="mt-0.5 text-xs text-slate-500">
              Once connected in Ghost, reload this page. PayGlue detects the connection automatically
              and will start granting complimentary paid memberships on purchase.
            </p>
          </div>
        </div>

        <div class="mt-4 rounded-lg border border-blue-100 bg-blue-50 p-3">
          <p class="text-xs font-medium text-blue-800">Stripe not available in your country?</p>
          <p class="mt-0.5 text-xs text-blue-700">
            No problem. Use a different payment provider such as Polar to accept payments without Stripe.
            Customers are added as free members with a label, and the PayGlue JS Paywall snippet handles
            content access.
          </p>
        </div>
      </section>
    </div>
  </AppShell>
</template>

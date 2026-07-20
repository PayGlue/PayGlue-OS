// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { createCreemCheckoutSession, getTenantUsage, type TenantUsage } from '../lib/api'
import { PLAN_TIERS, planDisplayName } from '../lib/planUpgrade'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()

const usage = ref<TenantUsage | null>(null)
const loadingUsage = ref(false)
const billingAnnual = ref(false)
const startingCheckoutFor = ref<string | null>(null)
const errorMessage = ref<string | null>(null)
const successMessage = ref<string | null>(null)

const canWrite = computed(() => {
  const role = session.activeMembership?.role
  return role === 'owner' || role === 'billing_admin'
})

const currentPlanKey = computed(() => usage.value?.plan ?? null)
const isFoundingMember = computed(() => currentPlanKey.value === 'founding')
// PG-210: null for accounts created before the stamp existed, which is why the
// banner still has a wording that works without a number.
const foundingMonthly = computed(() => usage.value?.founding_monthly_eur ?? null)

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) throw new Error('Tenant context is missing.')
  return { tenantSlug: session.activeTenantSlug, token: session.idToken }
}

const loadUsage = async () => {
  loadingUsage.value = true
  try {
    const { tenantSlug, token } = context()
    usage.value = await getTenantUsage(tenantSlug, token)
  } catch {
    // Non-fatal -- the plan cards still render, just without a "Current plan" badge.
  } finally {
    loadingUsage.value = false
  }
}

onMounted(loadUsage)

const startCheckout = async (planKey: 'solo' | 'studio' | 'agency') => {
  errorMessage.value = null
  successMessage.value = null
  startingCheckoutFor.value = planKey
  try {
    const { tenantSlug, token } = context()
    const returnUrl = `${window.location.origin}/t/${tenantSlug}/billing`
    const result = await createCreemCheckoutSession(tenantSlug, token, {
      planKey,
      interval: billingAnnual.value ? 'annual' : 'monthly',
      returnUrl,
    })
    if ('checkout_url' in result) {
      window.location.href = result.checkout_url
      return
    }
    // Already had a subscription -- switched in place, no redirect needed.
    successMessage.value = `Switched to ${planDisplayName(planKey)}. The price difference is billed with your existing payment method.`
    startingCheckoutFor.value = null
    await loadUsage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Could not start checkout.'
    startingCheckoutFor.value = null
  }
}
</script>

<template>
  <AppShell>
    <div class="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <div class="mb-8">
        <h1 class="text-2xl font-bold text-slate-900 dark:text-slate-100">Plans &amp; Pricing</h1>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Compare plans and upgrade or downgrade at any time. Changes apply immediately.
        </p>
      </div>

      <div v-if="errorMessage" class="mb-6 rounded-lg border border-rose-200 dark:border-rose-500/30 bg-rose-50 dark:bg-rose-500/10 p-3 text-sm text-rose-700 dark:text-rose-300">
        {{ errorMessage }}
      </div>

      <div v-if="successMessage" class="mb-6 rounded-lg border border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-300">
        {{ successMessage }}
      </div>

      <div v-if="isFoundingMember" class="mb-6 flex items-start gap-3 rounded-lg border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 p-4 text-sm text-amber-800 dark:text-amber-300">
        <svg class="mt-0.5 h-5 w-5 shrink-0 text-amber-500" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 9v4m0 4h.01M10.29 3.86l-8.02 13.9A1.5 1.5 0 003.55 20h16.9a1.5 1.5 0 001.28-2.24l-8.02-13.9a1.5 1.5 0 00-2.56 0z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <p>
          <strong>You're a Founding Member.</strong> Unlimited everything, locked in for life
          <template v-if="foundingMonthly">at {{ foundingMonthly }} €/month</template><template v-else>at your original rate</template>.
          Switching to Solo, Studio, or Agency below replaces that with a limited plan at a higher price, and can't be undone.
          You're welcome to switch, but there's usually no reason to.
        </p>
      </div>

      <div class="mb-8 flex items-center justify-center">
        <div class="relative inline-flex rounded-full bg-slate-100 dark:bg-slate-800 p-1">
          <button
            type="button"
            class="rounded-full px-4 py-1.5 text-sm transition-colors focus:outline-none"
            :class="!billingAnnual ? 'bg-white font-semibold text-slate-900 dark:bg-slate-700 dark:text-slate-100 shadow-sm' : 'text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:text-slate-300'"
            @click="billingAnnual = false"
          >
            Monthly
          </button>
          <button
            type="button"
            class="rounded-full px-4 py-1.5 text-sm transition-colors focus:outline-none"
            :class="billingAnnual ? 'bg-white font-semibold text-slate-900 dark:bg-slate-700 dark:text-slate-100 shadow-sm' : 'text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:text-slate-300'"
            @click="billingAnnual = true"
          >
            Yearly
          </button>
        </div>
        <span
          v-if="billingAnnual"
          class="absolute left-full ml-3 inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:text-emerald-300"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M10 6.5V17M10 6.5c-.5-1.5-1.8-3-3.5-3S3.5 4.7 3.5 6.5 5 8.5 6.5 8.5h7c1.5 0 3-1 3-2.5S15.2 3.5 13.5 3.5 10.5 5 10 6.5Z" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
            <rect x="3.5" y="8.5" width="13" height="3" rx="0.5" stroke="currentColor" stroke-width="1.4"/>
            <path d="M4 11.5v4.2c0 .72.58 1.3 1.3 1.3h9.4c.72 0 1.3-.58 1.3-1.3v-4.2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          Two months free
        </span>
      </div>

      <div class="grid grid-cols-1 gap-6 sm:grid-cols-3">
        <div
          v-for="tier in PLAN_TIERS"
          :key="tier.key"
          class="relative flex flex-col rounded-2xl border bg-white p-6 dark:border-slate-800 dark:bg-slate-900"
          :class="tier.key === currentPlanKey ? 'border-indigo-300 ring-2 ring-indigo-100' : 'border-slate-200 dark:border-slate-800'"
        >
          <span
            v-if="tier.key === currentPlanKey"
            class="absolute right-6 top-6 rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-semibold text-indigo-700 dark:text-indigo-300"
          >
            Current plan
          </span>

          <p class="text-xs font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">{{ tier.name }}</p>
          <p class="mt-3 flex items-baseline gap-1">
            <span class="text-3xl font-bold text-slate-900 dark:text-slate-100">{{ billingAnnual ? tier.annual : tier.monthly }} €</span>
            <span class="text-sm text-slate-400 dark:text-slate-500">/{{ billingAnnual ? 'yr' : 'mo' }}</span>
          </p>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ tier.tagline }}</p>

          <ul class="mt-5 flex-1 space-y-2">
            <li v-for="feature in tier.features" :key="feature" class="flex items-start gap-2 text-sm text-slate-600 dark:text-slate-300">
              <span class="mt-0.5 text-emerald-500">✓</span>
              {{ feature }}
            </li>
          </ul>

          <button
            v-if="tier.key === currentPlanKey"
            type="button"
            disabled
            class="mt-6 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 dark:border-slate-800 dark:bg-slate-800/40 px-4 py-2 text-sm font-semibold text-slate-400 dark:text-slate-500"
          >
            Current plan
          </button>
          <button
            v-else-if="canWrite"
            type="button"
            :disabled="startingCheckoutFor === tier.key"
            class="mt-6 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-60"
            @click="startCheckout(tier.key)"
          >
            {{ startingCheckoutFor === tier.key ? 'Starting checkout…' : `Switch to ${tier.name}` }}
          </button>
          <p v-else class="mt-6 text-xs text-slate-400 dark:text-slate-500">
            Your role can view plans but cannot make changes.
          </p>
        </div>
      </div>

      <p class="mt-6 text-center text-xs text-slate-400 dark:text-slate-500">
        First plan: you'll be redirected to Creem to complete your purchase, then brought back here.
        Switching an existing plan happens immediately, billed with proration.
      </p>
    </div>
  </AppShell>
</template>

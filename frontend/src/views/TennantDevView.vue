// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

const pricingPayload = {
  title: 'PayGlue Pricing (Dev)',
  subtitle: 'Embed validation page for Polar pricing integration.',
  plans: [
    {
      id: 'beta',
      name: 'Beta',
      price: 'Free',
      description: 'Early access while invite gate is active.',
      features: ['Join waitlist', 'Ghost entitlement sync', 'Early beta onboarding'],
      ctaLabel: 'Join Waitlist',
    },
    {
      id: 'founder',
      name: 'Founder',
      price: '$149',
      description: 'Founder access tier for early adopter teams.',
      features: ['Coexistence migration support', 'Webhook replay workflow', 'Priority onboarding support'],
      ctaLabel: 'Apply as Member',
    },
  ],
}

onMounted(() => {
  ;(window as Window & { PayGluePricing?: unknown }).PayGluePricing = pricingPayload

  const script = document.createElement('script')
  script.src = '/pricing-table.js'
  script.defer = true
  script.dataset.payGluePricingScript = 'true'
  document.body.appendChild(script)
})

onBeforeUnmount(() => {
  const script = document.querySelector('script[data-payglue-pricing-script="true"]')
  script?.parentElement?.removeChild(script)
})
</script>

<template>
  <main class="min-h-screen bg-slate-50 px-4 py-8 sm:px-6">
    <section class="mx-auto max-w-6xl space-y-4">
      <header class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <p class="text-xs font-semibold uppercase tracking-[0.12em] text-blue-600">Tennant Dev</p>
        <h1 class="mt-1 text-2xl font-semibold text-slate-900">Pricing Embed Development Page</h1>
        <p class="mt-1 text-sm text-slate-600">
          This page is used to validate the hosted `pricing-table.js` render and Polar pricing wiring.
        </p>
      </header>

      <div id="payglue-pricing-table"></div>
    </section>
  </main>
</template>

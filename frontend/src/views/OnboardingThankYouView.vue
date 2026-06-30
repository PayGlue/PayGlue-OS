// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PayGlueLogo from '../components/PayGlueLogo.vue'

const route = useRoute()
const router = useRouter()
const tenantSlug = String(route.params.tenantSlug ?? '')

const selectedProvider = localStorage.getItem(`payglue:provider:${tenantSlug}`) ?? 'polar'

const providerLabels: Record<string, string> = {
  polar: 'Polar',
  stripe: 'Stripe',
  mollie: 'Mollie',
  paypal: 'PayPal',
  paddle: 'Paddle',
  gumroad: 'Gumroad',
}

const providerLabel = providerLabels[selectedProvider] ?? 'your payment provider'

const continueSetup = () => {
  localStorage.setItem(`pg_ty_${tenantSlug}`, '1')
  router.push(`/t/${tenantSlug}/integrations`)
}

onMounted(() => {
  localStorage.setItem(`pg_ty_${tenantSlug}`, '1')
})
</script>

<template>
  <div class="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-6 py-16">
    <div class="mb-10 text-center">
      <PayGlueLogo size="lg" />
    </div>

    <div class="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-sm text-center">
      <div class="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 ring-4 ring-emerald-100">
        <svg class="h-7 w-7 text-emerald-600" viewBox="0 0 24 24" fill="none">
          <path d="M5 13l4 4L19 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>

      <h1 class="mb-2 text-xl font-bold text-slate-900">You're in. Thank you.</h1>
      <p class="mb-6 text-sm leading-relaxed text-slate-500">
        We built PayGlue because we needed it ourselves. You're one of the first — and that means a lot to us.
        If anything feels off, reply directly to your welcome email. It goes straight to us.
      </p>

      <button
        class="w-full rounded-xl bg-indigo-600 py-3 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700"
        @click="continueSetup"
      >
        Set up {{ providerLabel }} integration
      </button>

      <button
        class="mt-3 w-full rounded-xl border border-slate-200 py-3 text-sm text-slate-500 hover:bg-slate-50"
        @click="router.push(`/t/${tenantSlug}/dashboard`)"
      >
        Go to dashboard
      </button>
    </div>

    <p class="mt-6 text-xs text-slate-400">PayGlue.io · Made in Germany</p>
  </div>
</template>

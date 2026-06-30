// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { supabase } from '../lib/supabase'

const status = ref<'loading' | 'error'>('loading')
const errorMessage = ref('')

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  const checkoutId = params.get('checkout_id')

  if (!checkoutId) {
    status.value = 'error'
    errorMessage.value = 'No checkout ID found. Please contact support.'
    return
  }

  const { data, error } = await supabase.functions.invoke('verify-checkout', {
    body: { checkout_id: checkoutId },
  })

  if (error || !data?.action_link) {
    status.value = 'error'
    errorMessage.value = 'We could not verify your purchase. Please contact support@payglue.io'
    return
  }

  window.location.href = data.action_link
})
</script>

<template>
  <main class="flex min-h-screen flex-col items-center justify-center bg-slate-950 px-6">
    <div class="mb-8 text-xl font-bold tracking-tight text-white">PayGlue</div>

    <div v-if="status === 'loading'" class="text-center">
      <div class="mb-4 h-8 w-8 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent mx-auto"></div>
      <p class="text-sm text-slate-400">Setting up your account...</p>
    </div>

    <div v-else class="max-w-sm text-center">
      <p class="mb-2 text-sm font-semibold text-red-400">Something went wrong</p>
      <p class="text-sm text-slate-400">{{ errorMessage }}</p>
    </div>
  </main>
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { PageHeader, UiCard, UiButton, StatusPill, EmptyState, ProviderLogo } from '../components/ui'
import { PROVIDER_BRAND } from '../lib/providers'
import { listMappings, testMapping, type TestMappingResult } from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { ProductMapping } from '../types/api'

const hasLogo = (key: string) => key in PROVIDER_BRAND

const session = useSessionStore()
const mappings = ref<ProductMapping[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

// PG-193: send a synthetic event through the real pipeline to verify a
// connection end to end without a real purchase.
const testTarget = ref<ProductMapping | null>(null)
const testEmail = ref('')
const testRunning = ref(false)
const testResult = ref<TestMappingResult | null>(null)
const testError = ref<string | null>(null)

const openTest = (m: ProductMapping) => {
  testTarget.value = m
  testEmail.value = session.user?.email ?? ''
  testResult.value = null
  testError.value = null
}

const closeTest = () => {
  testTarget.value = null
  testRunning.value = false
}

const runTest = async () => {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token || !testTarget.value) return
  testRunning.value = true
  testResult.value = null
  testError.value = null
  try {
    testResult.value = await testMapping(slug, token, testTarget.value.id, testEmail.value.trim())
  } catch (e) {
    testError.value = e instanceof Error ? e.message : 'Test failed to run.'
  } finally {
    testRunning.value = false
  }
}

const load = async () => {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  loading.value = true
  error.value = null
  try {
    mappings.value = await listMappings(slug, token)
  } catch {
    error.value = 'Could not load mappings.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => session.activeTenantSlug, load)

const eventLabel = (e: string) => e === 'order.paid' ? 'One-time' : e === 'subscription.active' ? 'Subscription' : e
const emailLabel = (t: string | undefined) => {
  if (!t || t === 'none') return 'None'
  if (t === 'signin') return 'Magic Link'
  if (t === 'signup') return 'Sign-up'
  if (t === 'subscribe') return 'Subscribe'
  return t
}
const sourceLabel = (m: ProductMapping) => {
  const meta = m.metadata as any
  if (!meta?.source_type) return null
  const labels: Record<string, string> = { button: 'Buy Button', paywall: 'Paywall', pricing_table: 'Pricing Table' }
  const type = labels[meta.source_type] ?? meta.source_type
  const name = meta.source_name ? `: ${meta.source_name}` : ''
  const tier = meta.source_tier ? ` · ${meta.source_tier}` : ''
  return `${type}${name}${tier}`
}
</script>

<template>
  <AppShell>
    <div class="space-y-5">
      <PageHeader title="Product Mapping" description="Ghost actions assigned to each product. Edit them in the Button, Paywall, or Pricing Table editors." />

      <p v-if="loading" class="px-1 text-sm text-slate-500 dark:text-slate-400">Loading...</p>
      <p v-else-if="error" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">{{ error }}</p>

      <UiCard v-else-if="mappings.length === 0" :padded="false">
        <EmptyState title="No mappings configured yet" message="Link a product in the Buy Button, Paywall, or Pricing Table editor to create a mapping.">
          <template #icon>
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none"><path d="M5 12l4 4L19 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
          </template>
        </EmptyState>
      </UiCard>

      <UiCard v-else :padded="false">
        <div class="overflow-x-auto">
          <table class="w-full min-w-[720px] text-sm">
            <thead class="border-b border-slate-100 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-800/40">
              <tr>
                <th class="px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Provider</th>
                <th class="px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Product ID</th>
                <th class="px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Used in</th>
                <th class="px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Trigger</th>
                <th class="px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Welcome email</th>
                <th class="px-4 py-3 text-left text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Status</th>
                <th class="px-4 py-3 text-right text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Test</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
              <tr v-for="m in mappings" :key="m.id" class="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                <td class="px-4 py-3">
                  <span class="flex items-center gap-2">
                    <ProviderLogo v-if="hasLogo(m.payment_provider)" :provider="m.payment_provider" size="sm" />
                    <span class="font-medium capitalize text-slate-700 dark:text-slate-200">{{ m.payment_provider }}</span>
                  </span>
                </td>
                <td class="px-4 py-3 font-mono text-xs text-slate-500 dark:text-slate-400">{{ m.external_product_id }}</td>
                <td class="px-4 py-3">
                  <span v-if="sourceLabel(m)" class="text-sm text-slate-700 dark:text-slate-200">{{ sourceLabel(m) }}</span>
                  <span v-else class="text-xs text-slate-400 dark:text-slate-500">-</span>
                </td>
                <td class="px-4 py-3 text-slate-700 dark:text-slate-200">{{ eventLabel(m.event_type) }}</td>
                <td class="px-4 py-3 text-slate-700 dark:text-slate-200">{{ emailLabel((m.metadata as any)?.ghost_email_type) }}</td>
                <td class="px-4 py-3">
                  <StatusPill :tone="m.is_active ? 'good' : 'neutral'">{{ m.is_active ? 'Active' : 'Inactive' }}</StatusPill>
                </td>
                <td class="px-4 py-3 text-right">
                  <UiButton
                    size="sm"
                    variant="default"
                    :disabled="!m.is_active"
                    :title="m.is_active ? 'Send a test event through the full pipeline' : 'Activate the mapping to test it'"
                    @click="openTest(m)"
                  >
                    Send test
                  </UiButton>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </UiCard>
    </div>

    <!-- PG-193: test-event modal -->
    <div
      v-if="testTarget"
      class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 px-4"
      @click.self="closeTest"
    >
      <div class="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-800 dark:bg-slate-900">
        <h2 class="text-base font-semibold text-slate-900 dark:text-slate-100">Send a test event</h2>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Simulates a
          <span class="font-medium text-slate-700 dark:text-slate-200">{{ eventLabel(testTarget.event_type) }}</span>
          event for
          <span class="font-mono text-xs text-slate-600 dark:text-slate-300">{{ testTarget.external_product_id }}</span>
          ({{ testTarget.payment_provider }}) through the full pipeline, with no real purchase needed.
        </p>
        <p class="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
          This grants real access to the address below in your Ghost site. Use an email you control (e.g. <span class="font-medium">you+test@yourdomain.com</span>).
        </p>

        <label class="mt-4 block text-xs font-medium text-slate-600 dark:text-slate-300">Test email</label>
        <input
          v-model="testEmail"
          type="email"
          placeholder="you+test@yourdomain.com"
          class="pg-input mt-1"
          @keyup.enter="runTest"
        />

        <!-- Result -->
        <div v-if="testResult?.ok" class="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
          ✅ Test member granted in Ghost ({{ testResult.entitlements.map(e => e.entitlement_key).join(', ') }}). Check your Ghost members list to confirm.
        </div>
        <div v-else-if="testResult && !testResult.ok" class="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          ❌ {{ testResult.error }}
        </div>
        <div v-else-if="testError" class="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          {{ testError }}
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <UiButton variant="ghost" @click="closeTest">Close</UiButton>
          <UiButton variant="primary" :disabled="testRunning || !testEmail.trim()" @click="runTest">
            {{ testRunning ? 'Sending…' : 'Send test event' }}
          </UiButton>
        </div>
      </div>
    </div>
  </AppShell>
</template>

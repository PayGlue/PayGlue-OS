// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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

/**
 * One entry per product, which since PG-254 is also one rule per product.
 *
 * A product can still hold two rules, because a grant on a purchase and a
 * revoke on a cancellation are two different things to say about it. They
 * belong on one line: somebody reading this wants to know what happens when
 * this is bought, not how many rows the table has.
 */
interface ProductRow {
  key: string
  provider: string
  productId: string
  grant?: ProductMapping
  revoke?: ProductMapping
  usedIn: string[]
}

const rows = computed<ProductRow[]>(() => {
  const byProduct = new Map<string, ProductRow>()
  for (const m of mappings.value) {
    const key = `${m.payment_provider}::${m.external_product_id}`
    const row = byProduct.get(key) ?? {
      key,
      provider: m.payment_provider,
      productId: m.external_product_id,
      usedIn: [],
    }
    if (m.action === 'revoke') row.revoke = m
    else row.grant = m
    if (m.used_in?.length) row.usedIn = m.used_in
    byProduct.set(key, row)
  }
  return [...byProduct.values()]
})

const WELCOME_EMAIL: Record<string, string> = {
  signin: 'a magic-link email',
  signup: 'a sign-up email',
  subscribe: 'a subscription email',
}

const firstEmailType = (m: ProductMapping): string | undefined => {
  const meta = m.metadata as { ghost_email_types?: string[]; ghost_email_type?: string | null }
  return meta?.ghost_email_types?.[0] ?? meta?.ghost_email_type ?? undefined
}

/**
 * What buying this actually does, written as a sentence.
 *
 * The screen used to print the columns of the table: entitlement key, event
 * type, action, quantity, active. Those are the fields of a unique constraint,
 * and nobody opens this page asking about a unique constraint. They open it
 * asking "what happens when somebody buys this", and none of those columns
 * answered it directly (PG-255).
 */
const sentence = (row: ProductRow): string => {
  if (!row.grant) return 'Nothing is granted for this product. Only a cancellation rule exists.'
  const meta = row.grant.metadata as { ghost_subscribed?: boolean }
  const parts = [`Buying this grants access in Ghost and labels the member ${ghostLabel(row.grant)}`]
  parts.push(
    meta?.ghost_subscribed === false
      ? 'without subscribing them to your newsletter'
      : 'and subscribes them to your newsletter',
  )
  const email = firstEmailType(row.grant)
  const tail = email && WELCOME_EMAIL[email]
    ? `They receive ${WELCOME_EMAIL[email]}.`
    : 'No welcome email is sent.'
  return `${parts.join(', ')}. ${tail}`
}

/** Mirrors what the Ghost adapter writes, so the page names the real label. */
const ghostLabel = (m: ProductMapping) =>
  `product:${m.entitlement_key.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')}`
</script>

<template>
  <AppShell>
    <div class="space-y-5">
      <PageHeader title="Product Mapping" description="What happens in Ghost when somebody buys one of your products. Change it where you picked the product: the Button, Paywall, or Pricing Table editor." />

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
        <ul class="divide-y divide-slate-100 dark:divide-slate-800">
          <li v-for="row in rows" :key="row.key" class="px-4 py-4 sm:px-5">
            <div class="flex flex-wrap items-start gap-3">
              <ProviderLogo v-if="hasLogo(row.provider)" :provider="row.provider" size="sm" />
              <div class="min-w-0 flex-1 space-y-1.5">
                <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span class="font-medium capitalize text-slate-800 dark:text-slate-100">{{ row.provider }}</span>
                  <span class="font-mono text-xs text-slate-400 dark:text-slate-500">{{ row.productId }}</span>
                  <span v-if="row.grant" class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {{ eventLabel(row.grant.event_type) }}
                  </span>
                  <StatusPill v-if="row.grant && !row.grant.is_active" tone="neutral">Paused</StatusPill>
                </div>

                <p class="text-sm leading-relaxed text-slate-700 dark:text-slate-200">{{ sentence(row) }}</p>

                <p v-if="row.revoke" class="text-sm text-slate-500 dark:text-slate-400">
                  A cancellation takes that access away again.
                </p>

                <p v-if="row.usedIn.length" class="text-xs text-slate-500 dark:text-slate-400">
                  Offered in {{ row.usedIn.join(' · ') }}
                </p>
                <p v-else class="text-xs text-slate-400 dark:text-slate-500">
                  Not offered in any widget. Sold elsewhere, or the widget was removed. Buying it still does the above.
                </p>
              </div>

              <UiButton
                v-if="row.grant"
                size="sm"
                variant="default"
                :disabled="!row.grant.is_active"
                :title="row.grant.is_active ? 'Send a test event through the full pipeline' : 'This rule is paused'"
                @click="openTest(row.grant)"
              >
                Send test
              </UiButton>
            </div>
          </li>
        </ul>
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

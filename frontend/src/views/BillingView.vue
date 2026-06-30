// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { getPolarSubscriptions, cancelPolarSubscription, getPolarInvoices } from '../lib/api'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()

const loadingSub = ref(false)
const loadingInvoices = ref(false)
const cancelling = ref(false)
const errorMessage = ref<string | null>(null)
const successMessage = ref<string | null>(null)
const showCancelDialog = ref(false)

const canWrite = computed(() => {
  const role = session.activeMembership?.role
  return role === 'owner' || role === 'billing_admin'
})

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) throw new Error('Tenant context is missing.')
  return { tenantSlug: session.activeTenantSlug, token: session.idToken }
}

type Sub = Record<string, unknown>
type Invoice = Record<string, unknown>

const subscriptions = ref<Sub[]>([])
const invoices = ref<Invoice[]>([])

const activeSub = computed(() =>
  subscriptions.value.find((s) => {
    const st = s.status as string
    return st === 'active' || st === 'trialing'
  }) ?? subscriptions.value[0] ?? null,
)

const latestOrder = computed(() => invoices.value[0] ?? null)

const portalUrl = computed(() => {
  const isSandbox = activeSub.value?._sandbox ?? latestOrder.value?._sandbox ?? false
  return isSandbox ? 'https://sandbox.polar.sh/nafdo/portal' : 'https://polar.sh/nafdo/portal'
})

const formatDate = (iso: unknown): string => {
  if (!iso || typeof iso !== 'string') return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

const formatAmount = (amount: unknown, currency: unknown): string => {
  if (amount == null) return '—'
  const num = typeof amount === 'number' ? amount / 100 : Number(amount) / 100
  const cur = typeof currency === 'string' ? currency.toUpperCase() : 'EUR'
  return new Intl.NumberFormat('en-DE', { style: 'currency', currency: cur }).format(num)
}

const statusBadgeClass = (st: unknown): string => {
  if (st === 'active') return 'bg-emerald-100 text-emerald-700'
  if (st === 'trialing') return 'bg-indigo-100 text-indigo-700'
  if (st === 'canceled' || st === 'cancelled') return 'bg-slate-100 text-slate-500'
  return 'bg-amber-100 text-amber-700'
}

const loadSubscription = async () => {
  loadingSub.value = true
  try {
    const { tenantSlug, token } = context()
    const res = await getPolarSubscriptions(tenantSlug, token)
    subscriptions.value = res.subscriptions
  } catch {
    // non-fatal
  } finally {
    loadingSub.value = false
  }
}

const loadInvoices = async () => {
  loadingInvoices.value = true
  try {
    const { tenantSlug, token } = context()
    const res = await getPolarInvoices(tenantSlug, token)
    invoices.value = res.invoices
  } catch {
    // non-fatal
  } finally {
    loadingInvoices.value = false
  }
}

const confirmCancel = async () => {
  const sub = activeSub.value
  if (!sub) return
  cancelling.value = true
  errorMessage.value = null
  try {
    const { tenantSlug, token } = context()
    await cancelPolarSubscription(tenantSlug, token, sub.id as string, Boolean(sub._sandbox))
    showCancelDialog.value = false
    await loadSubscription()
    successMessage.value = 'Subscription will be cancelled at the end of the current billing period.'
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Could not cancel subscription.'
    showCancelDialog.value = false
  } finally {
    cancelling.value = false
  }
}

const openReceipt = (inv: Invoice) => {
  const url = typeof inv.receipt_url === 'string' && inv.receipt_url
    ? inv.receipt_url
    : (inv._sandbox ? 'https://sandbox.polar.sh/nafdo/portal' : 'https://polar.sh/nafdo/portal')
  window.open(url, '_blank', 'noopener')
}

onMounted(() => {
  loadSubscription()
  loadInvoices()
})
</script>

<template>
  <AppShell>
    <div class="space-y-6">

      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h1 class="text-xl font-semibold text-slate-900">Billing</h1>
        <p class="mt-1 text-sm text-slate-500">
          Your subscription and invoice history via Polar. To update payment details or manage your plan, use the Polar customer portal.
        </p>
        <p v-if="!canWrite" class="mt-3 text-xs text-amber-700">Your role can view billing but cannot make changes.</p>
        <p v-if="errorMessage" class="mt-3 text-sm text-rose-700">{{ errorMessage }}</p>
        <p v-if="successMessage" class="mt-3 text-sm text-emerald-700">{{ successMessage }}</p>
      </section>

      <!-- Subscription -->
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 class="mb-4 text-base font-semibold text-slate-900">Subscription</h2>

        <div v-if="loadingSub" class="text-sm text-slate-400">Loading...</div>

        <!-- No subscription but has purchases: show latest order as product card -->
        <div v-else-if="!activeSub && latestOrder" class="rounded-xl border border-slate-100 bg-slate-50 p-4">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div class="space-y-1">
              <p class="text-base font-semibold text-slate-900">
                {{ (latestOrder.product as Record<string, unknown>)?.name ?? 'PayGlue' }}
              </p>
              <p class="text-sm text-slate-500">
                {{ formatAmount(latestOrder.amount, latestOrder.currency) }} &middot; One-time purchase
              </p>
              <p class="text-xs text-slate-400">Purchased {{ formatDate(latestOrder.created_at) }}</p>
            </div>
            <div class="flex flex-wrap items-center gap-3">
              <span class="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">Active</span>
              <span v-if="latestOrder._sandbox" class="rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-semibold text-violet-700">
                Sandbox
              </span>
              <a
                :href="portalUrl"
                target="_blank"
                rel="noopener"
                class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
              >
                Customer portal ↗
              </a>
            </div>
          </div>
        </div>

        <!-- No subscription and no purchases -->
        <div v-else-if="!activeSub" class="rounded-xl border border-slate-100 bg-slate-50 p-4 text-sm text-slate-500">
          No active subscription found for this account.
          <a :href="portalUrl" target="_blank" rel="noopener" class="ml-2 font-semibold text-slate-700 hover:underline">Customer portal ↗</a>
        </div>

        <!-- Active subscription -->
        <div v-else class="rounded-xl border border-slate-100 bg-slate-50 p-4">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div class="space-y-1">
              <p class="text-base font-semibold text-slate-900">
                {{ (activeSub.product as Record<string, unknown>)?.name ?? 'PayGlue' }}
              </p>
              <p class="text-sm text-slate-500">
                {{ formatAmount(activeSub.amount, activeSub.currency) }} / {{ activeSub.recurring_interval ?? 'month' }}
              </p>
              <p v-if="activeSub.current_period_end" class="text-xs text-slate-400">
                Next billing: {{ formatDate(activeSub.current_period_end) }}
              </p>
              <p v-if="activeSub.cancel_at_period_end" class="text-xs font-medium text-amber-600">
                Cancels at end of period
              </p>
            </div>
            <div class="flex flex-wrap items-center gap-3">
              <span
                class="rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize"
                :class="statusBadgeClass(activeSub.status)"
              >
                {{ activeSub.status }}
              </span>
              <span v-if="activeSub._sandbox" class="rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-semibold text-violet-700">
                Sandbox
              </span>
              <button
                v-if="canWrite && activeSub.status === 'active' && !activeSub.cancel_at_period_end"
                class="rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                :disabled="cancelling"
                @click="showCancelDialog = true"
              >
                Cancel plan
              </button>
              <a
                :href="portalUrl"
                target="_blank"
                rel="noopener"
                class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
              >
                Change plan ↗
              </a>
              <a
                :href="portalUrl"
                target="_blank"
                rel="noopener"
                class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"
              >
                Customer portal ↗
              </a>
            </div>
          </div>
        </div>
      </section>

      <!-- Invoices -->
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 class="mb-4 text-base font-semibold text-slate-900">Invoice history</h2>

        <div v-if="loadingInvoices" class="text-sm text-slate-400">Loading...</div>

        <div v-else-if="!invoices.length" class="text-sm text-slate-400">No invoices yet.</div>

        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-slate-100 text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                <th class="pb-2 pr-4">Date</th>
                <th class="pb-2 pr-4">Product</th>
                <th class="pb-2 pr-4">Amount</th>
                <th class="pb-2">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="inv in invoices"
                :key="String(inv.id)"
                class="cursor-pointer border-b border-slate-50 last:border-0 hover:bg-slate-50"
                @click="openReceipt(inv)"
              >
                <td class="py-2.5 pr-4 text-slate-600">{{ formatDate(inv.created_at) }}</td>
                <td class="py-2.5 pr-4 text-slate-700">{{ (inv.product as Record<string, unknown>)?.name ?? '—' }}</td>
                <td class="py-2.5 pr-4 font-medium text-slate-900">{{ formatAmount(inv.amount, inv.currency) }}</td>
                <td class="py-2.5">
                  <div class="flex items-center gap-1.5">
                    <span class="rounded-full px-2 py-0.5 text-xs font-semibold capitalize" :class="statusBadgeClass(inv.status)">
                      {{ inv.status ?? 'paid' }}
                    </span>
                    <span v-if="inv._sandbox" class="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-semibold text-violet-700">
                      Sandbox
                    </span>
                    <svg class="ml-auto h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                    </svg>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Cancel dialog -->
      <Teleport to="body">
        <div
          v-if="showCancelDialog"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          @click.self="showCancelDialog = false"
        >
          <div class="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <h3 class="mb-2 text-base font-semibold text-slate-900">Cancel subscription?</h3>
            <p class="mb-5 text-sm text-slate-500">
              Your plan stays active until the end of the current billing period. You can resubscribe at any time.
            </p>
            <div class="flex gap-3">
              <button
                class="flex-1 rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                @click="showCancelDialog = false"
              >
                Keep plan
              </button>
              <button
                class="flex-1 rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
                :disabled="cancelling"
                @click="confirmCancel"
              >
                {{ cancelling ? 'Cancelling...' : 'Yes, cancel' }}
              </button>
            </div>
          </div>
        </div>
      </Teleport>

    </div>
  </AppShell>
</template>

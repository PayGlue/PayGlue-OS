// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { getTenantUsage, getCreemSubscription, getCreemInvoices, cancelCreemSubscription, type TenantUsage } from '../lib/api'
import { planDisplayName } from '../lib/planUpgrade'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()

const loadingBilling = ref(false)
const errorMessage = ref<string | null>(null)

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

const usage = ref<TenantUsage | null>(null)
const loadingUsage = ref(false)
const usageLabel = (limit: number | null): string => (limit === null ? 'Unlimited' : String(limit))

const subscriptions = ref<Sub[]>([])
const invoices = ref<Invoice[]>([])
const portalLink = ref<string | null>(null)

const activeSub = computed(() =>
  subscriptions.value.find((s) => {
    const st = s.status as string
    return st === 'active' || st === 'trialing'
  }) ?? subscriptions.value[0] ?? null,
)
const latestOrder = computed(() => invoices.value[0] ?? null)

const formatDate = (value: unknown): string => {
  // Creem timestamps are Unix epoch milliseconds (numbers), not ISO strings
  // like Polar's -- confirmed against a real transaction payload (PG-149).
  if (value == null) return '—'
  const date = typeof value === 'number' || typeof value === 'string' ? new Date(value) : null
  if (!date || Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

const formatAmount = (amount: unknown, currency: unknown): string => {
  if (amount == null) return '—'
  const num = typeof amount === 'number' ? amount / 100 : Number(amount) / 100
  const cur = typeof currency === 'string' ? currency.toUpperCase() : 'EUR'
  return new Intl.NumberFormat('en-DE', { style: 'currency', currency: cur }).format(num)
}

const statusDotClass = (st: unknown): string => {
  if (st === 'active') return 'bg-emerald-500'
  if (st === 'trialing') return 'bg-indigo-500'
  if (st === 'canceled' || st === 'cancelled') return 'bg-slate-400'
  return 'bg-amber-500'
}

// Summary tiles for the "Your Subscription" panel -- backed by whichever of
// an active subscription or a one-time order/transaction is on file.
//
// Confirmed against a real transaction payload (PG-149): Creem's
// /v1/subscriptions/search came back empty even for a customer with a real,
// active recurring subscription (that endpoint has no customer_id filter at
// all -- see PG-147 -- so a real subscription can simply be off page 1).
// The transaction itself is reliably customer-scoped though, and a
// recurring transaction carries a "subscription" id plus period_start/
// period_end (epoch ms), so treat any invoice with a "subscription" field
// as the recurring source when no subscription object was found -- a
// one-time Founding Member purchase has no "subscription" field at all and
// correctly falls through to the one-time label.
const subProduct = (source: Sub | Invoice | null): Record<string, unknown> | undefined => {
  const product = source?.product
  return typeof product === 'object' && product !== null ? (product as Record<string, unknown>) : undefined
}

const recurringSource = computed(() => {
  if (activeSub.value) return activeSub.value
  return latestOrder.value?.subscription ? latestOrder.value : null
})

const isYearlyInterval = (source: Sub): boolean => {
  const interval = (source.recurring_interval as string | undefined) ?? (source.billing_period as string | undefined)
  if (interval) return interval.includes('year')
  const start = source.period_start
  const end = source.period_end
  if (typeof start === 'number' && typeof end === 'number') {
    return (end - start) / 86_400_000 > 180
  }
  return false
}

const periodEnd = (source: Sub): unknown =>
  source.current_period_end ?? source.current_period_end_date ?? source.period_end

const planName = computed(() => {
  // Prefer our own BillingAccount.plan (Solo/Studio/Agency/Founding Member)
  // over Creem's checkout description -- Creem only ever returns a generic
  // "Subscription payment" here (confirmed against the real payload,
  // PG-149), not the actual plan tier.
  if (usage.value?.plan) return planDisplayName(usage.value.plan)
  const source = activeSub.value ?? latestOrder.value
  return (subProduct(source)?.name as string | undefined)
    ?? (typeof source?.product === 'string' ? source.product : undefined)
    ?? (source?.description as string | undefined)
    ?? 'PayGlue'
})

// PG-183: tester accounts (redeemed a PayGlue license code) have no Creem sub,
// so the panel shows a "Tester" state + access-window expiry instead.
const isTester = computed(() => usage.value?.is_tester === true)

// PG-210: the rate a Founding Member locked, captured at purchase. Until now
// every screen said "your original rate" without ever naming it, because
// nothing on the account knew the number.
const foundingTier = computed(() => usage.value?.founding_tier ?? null)
const foundingMonthly = computed(() => usage.value?.founding_monthly_eur ?? null)
const testerExpiry = computed(() => usage.value?.tester_access_expires_at ?? null)

const planSubtitle = computed(() => {
  if (isTester.value) return testerExpiry.value ? 'Tester access' : 'Tester access (no expiry)'
  if (recurringSource.value) return isYearlyInterval(recurringSource.value) ? 'Annual billing' : 'Monthly billing'
  if (latestOrder.value) return 'One-time purchase'
  return '—'
})

const statusLabel = computed(() => {
  if (isTester.value) return 'Tester'
  if (activeSub.value) return activeSub.value.status as string
  if (latestOrder.value) return 'active'
  return 'inactive'
})

const priceLabel = computed(() => {
  if (isTester.value) return 'Free'
  const source = activeSub.value ?? latestOrder.value
  if (!source) return '—'
  const rawAmount = source.amount ?? source.amount_paid ?? subProduct(source)?.price
  const amount = formatAmount(rawAmount, source.currency)
  if (recurringSource.value) {
    return `${amount}/${isYearlyInterval(recurringSource.value) ? 'yr' : 'mo'}`
  }
  return amount
})

const nextPaymentLabel = computed(() => {
  if (isTester.value) return testerExpiry.value ? formatDate(testerExpiry.value) : 'Never expires'
  const end = recurringSource.value ? periodEnd(recurringSource.value) : undefined
  if (end) return formatDate(end)
  if (latestOrder.value) return 'One-time'
  return '—'
})

const loadUsage = async () => {
  loadingUsage.value = true
  try {
    const { tenantSlug, token } = context()
    usage.value = await getTenantUsage(tenantSlug, token)
  } catch {
    // non-fatal
  } finally {
    loadingUsage.value = false
  }
}

const loadBilling = async () => {
  loadingBilling.value = true
  errorMessage.value = null
  try {
    const { tenantSlug, token } = context()
    const [subRes, invRes] = await Promise.all([
      getCreemSubscription(tenantSlug, token),
      getCreemInvoices(tenantSlug, token),
    ])
    subscriptions.value = subRes.subscriptions
    invoices.value = invRes.invoices
    portalLink.value = subRes.portal_link ?? invRes.portal_link ?? null
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Unable to load billing.'
  } finally {
    loadingBilling.value = false
  }
}

const cancelEffectsAcknowledged = ref(false)
const cancelling = ref(false)
const cancelError = ref<string | null>(null)
const cancelResult = ref<Record<string, unknown> | null>(null)
const cancelEffectiveDate = computed(() => {
  const source = cancelResult.value
  if (!source) return null
  const date = source.current_period_end_date ?? source.current_period_end ?? source.canceled_at
  return date ? formatDate(date) : null
})

const cancelSubscription = async () => {
  cancelling.value = true
  cancelError.value = null
  try {
    const { tenantSlug, token } = context()
    cancelResult.value = await cancelCreemSubscription(tenantSlug, token)
    cancelEffectsAcknowledged.value = false
    await loadBilling()
  } catch (e) {
    cancelError.value = e instanceof Error ? e.message : 'Could not cancel subscription.'
  } finally {
    cancelling.value = false
  }
}

const openReceipt = (inv: Invoice) => {
  const url = typeof inv.receipt_url === 'string' && inv.receipt_url ? inv.receipt_url : portalLink.value
  if (url) window.open(url, '_blank', 'noopener')
}

const invoiceLabel = (inv: Invoice): string =>
  (subProduct(inv)?.name as string | undefined) ?? (inv.description as string | undefined) ?? '—'
// "amount" is the real charge amount; "amount_paid" was 0 on a genuinely
// paid transaction in the real payload (PG-149) -- ?? only falls through on
// null/undefined, so amount_paid=0 was winning and showing "0,00 €" for a
// paid 19€ invoice. amount first, amount_paid only as a fallback if amount
// itself is missing.
const invoiceAmount = (inv: Invoice): unknown => inv.amount ?? inv.amount_paid
const invoiceIsRefunded = (inv: Invoice): boolean => Number(inv.refunded_amount ?? 0) > 0
const invoiceStatusLabel = (inv: Invoice): string => (invoiceIsRefunded(inv) ? 'Refunded' : 'Paid')
const invoiceStatusClass = (inv: Invoice): string =>
  invoiceIsRefunded(inv) ? 'bg-amber-100 text-amber-700 dark:text-amber-300' : 'bg-emerald-100 text-emerald-700 dark:text-emerald-300'

onMounted(() => {
  loadBilling()
  loadUsage()
})
</script>

<template>
  <AppShell>
    <div class="space-y-6">

      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">Billing</h1>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Your subscription and invoice history via Creem. To update payment details or manage your plan, use the Creem customer portal.
        </p>
        <p v-if="!canWrite" class="mt-3 text-xs text-amber-700 dark:text-amber-300">Your role can view billing but cannot make changes.</p>
        <p v-if="errorMessage" class="mt-3 text-sm text-rose-700 dark:text-rose-300">{{ errorMessage }}</p>
      </section>

      <!-- Usage -->
      <section v-if="usage" class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="mb-1 text-base font-semibold text-slate-900 dark:text-slate-100">Usage</h2>
        <p class="mb-4 text-sm text-slate-500 dark:text-slate-400">What you're using on your current plan.</p>

        <div v-if="loadingUsage" class="text-sm text-slate-400 dark:text-slate-500">Loading...</div>

        <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div v-for="(item, key) in usage.usage" :key="key" class="rounded-xl bg-slate-50 dark:bg-slate-800/40 p-4">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">{{ String(key).replace('_', ' ') }}</p>
            <p class="mt-1.5 text-lg font-semibold text-slate-900 dark:text-slate-100">{{ item.used }} / {{ usageLabel(item.limit) }}</p>
          </div>
        </div>
      </section>

      <!-- Subscription -->
      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="mb-4 text-base font-semibold text-slate-900 dark:text-slate-100">Your Subscription</h2>

        <div v-if="loadingBilling" class="text-sm text-slate-400 dark:text-slate-500">Loading...</div>

        <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div class="rounded-xl border border-slate-100 dark:border-slate-800 p-4">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">Plan</p>
            <p class="mt-1.5 break-words text-lg font-semibold leading-snug text-slate-900 dark:text-slate-100">{{ planName }}</p>
            <p class="mt-0.5 text-xs text-slate-400 dark:text-slate-500">{{ planSubtitle }}</p>
          </div>
          <div class="rounded-xl border border-slate-100 dark:border-slate-800 p-4">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">Status</p>
            <p class="mt-1.5 flex items-center gap-2 text-lg font-semibold capitalize text-slate-900 dark:text-slate-100">
              {{ statusLabel }}
              <span class="h-2 w-2 rounded-full" :class="statusDotClass(isTester ? 'trialing' : (activeSub?.status ?? (latestOrder ? 'active' : 'inactive')))" />
            </p>
            <p v-if="isTester" class="mt-0.5 text-xs font-medium text-violet-600">PayGlue tester</p>
            <p v-else-if="(activeSub ?? latestOrder)?._sandbox" class="mt-0.5 text-xs font-medium text-violet-600">Sandbox</p>
          </div>
          <div class="rounded-xl border border-slate-100 dark:border-slate-800 p-4">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">{{ isTester ? 'Access Ends' : 'Next Payment' }}</p>
            <p class="mt-1.5 text-lg font-semibold text-slate-900 dark:text-slate-100">{{ nextPaymentLabel }}</p>
          </div>
          <div class="rounded-xl border border-slate-100 dark:border-slate-800 p-4">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">Price</p>
            <p class="mt-1.5 text-lg font-semibold text-slate-900 dark:text-slate-100">{{ priceLabel }}</p>
            <p class="mt-0.5 text-xs text-slate-400 dark:text-slate-500">{{ isTester ? 'PayGlue tester code' : 'Billed via Creem' }}</p>
          </div>
        </div>

        <div v-if="foundingMonthly" class="mt-4 rounded-xl border border-indigo-200 bg-indigo-50 p-4 dark:border-indigo-500/30 dark:bg-indigo-500/10">
          <p class="text-sm font-medium text-indigo-800 dark:text-indigo-300">
            You're a Founding Member<template v-if="foundingTier"> from batch {{ foundingTier }}</template>.
            Your rate is <strong>{{ foundingMonthly }} €/month</strong>, locked for life.
          </p>
          <p class="mt-1 text-sm text-indigo-700 dark:text-indigo-300/80">
            It never rises, whatever PayGlue costs later. Cancelling gives it up, and coming back means the price of
            that day.
          </p>
        </div>

        <div v-if="isTester" class="mt-4 rounded-xl border border-violet-200 bg-violet-50 p-4 dark:border-violet-500/30 dark:bg-violet-500/10">
          <p class="text-sm font-medium text-violet-800 dark:text-violet-300">
            <template v-if="testerExpiry">You're on a free tester code until {{ nextPaymentLabel }}.</template>
            <template v-else>You're on a free tester code with no expiry.</template>
          </p>
          <p class="mt-1 text-sm text-violet-700 dark:text-violet-300/80">
            Pick a plan any time to keep your setup running{{ testerExpiry ? ' after your tester access ends' : '' }}.
            <RouterLink :to="`/t/${session.activeTenantSlug}/plans`" class="font-semibold underline underline-offset-2">View plans</RouterLink>
          </p>
        </div>

        <p v-if="!activeSub && !latestOrder && !isTester" class="mt-4 text-sm text-slate-500 dark:text-slate-400">
          No active subscription found for this account.
        </p>
        <p v-if="activeSub?.cancel_at_period_end" class="mt-4 text-sm font-medium text-amber-600 dark:text-amber-400">
          Cancels at the end of the current billing period.
        </p>
      </section>

      <!-- Subscription actions -->
      <section v-if="portalLink && (activeSub || latestOrder)" class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="text-base font-semibold text-slate-900 dark:text-slate-100">Subscription actions</h2>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Change your billing cycle or update payment details via the Creem customer portal.</p>

        <div class="mt-4 flex flex-wrap items-center gap-3">
          <a
            :href="portalLink"
            target="_blank"
            rel="noopener"
            class="inline-flex items-center gap-2 rounded-full border border-slate-200 dark:border-slate-800 px-4 py-2 text-sm font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800/40"
          >
            <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
            </svg>
            Manage on Creem
          </a>
        </div>
      </section>

      <!-- Danger zone -->
      <section v-if="canWrite && activeSub && !cancelResult" class="rounded-2xl border border-rose-200 dark:border-rose-500/30 bg-white p-5 shadow-sm dark:border-rose-500/30 dark:bg-slate-900">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-rose-600 dark:text-rose-400">Danger zone</h2>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Cancel your subscription. You'll keep access until the end of the current billing period, then it ends. There is no partial refund.</p>

        <p v-if="cancelError" class="mt-3 text-sm text-rose-700 dark:text-rose-300">{{ cancelError }}</p>

        <!-- Step 1: effects acknowledgement -->
        <div v-if="!cancelEffectsAcknowledged" class="mt-3 space-y-3">
          <div class="rounded-xl border border-rose-200 dark:border-rose-500/30 bg-rose-50 dark:bg-rose-500/10 p-4 text-sm text-rose-900">
            <p class="font-semibold mb-2">Canceling means:</p>
            <ul class="space-y-1 list-disc list-inside text-rose-800 dark:text-rose-300">
              <li>Your plan keeps working until {{ nextPaymentLabel }}, then it stops renewing</li>
              <li>After that date, your account drops to whatever the free tier allows: buy buttons, paywalls, and pricing tables over that limit stop working</li>
              <li>You can resubscribe any time before or after</li>
            </ul>
          </div>
          <button
            type="button"
            class="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 dark:text-rose-300 transition-colors hover:bg-rose-50"
            @click="cancelEffectsAcknowledged = true"
          >
            I have read and understand these effects
          </button>
        </div>

        <!-- Step 2: final confirm -->
        <div v-else class="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            class="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="cancelling"
            @click="cancelSubscription"
          >
            {{ cancelling ? 'Canceling…' : 'Cancel subscription' }}
          </button>
          <button
            type="button"
            class="rounded-lg border border-slate-300 dark:border-slate-700 px-4 py-2 text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40"
            @click="cancelEffectsAcknowledged = false"
          >
            Never mind
          </button>
        </div>
      </section>

      <section v-else-if="cancelResult" class="rounded-2xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 p-5 shadow-sm">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300">Subscription canceled</h2>
        <p class="mt-1 text-sm text-amber-800 dark:text-amber-300">
          Your subscription won't renew.
          <template v-if="cancelEffectiveDate">You'll keep access until {{ cancelEffectiveDate }}.</template>
        </p>
      </section>

      <!-- Invoices -->
      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="mb-4 text-base font-semibold text-slate-900 dark:text-slate-100">Invoice history</h2>

        <div v-if="loadingBilling" class="text-sm text-slate-400 dark:text-slate-500">Loading...</div>

        <div v-else-if="!invoices.length" class="text-sm text-slate-400 dark:text-slate-500">No invoices yet.</div>

        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-slate-100 dark:border-slate-800 text-left text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
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
                class="cursor-pointer border-b border-slate-50 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/40"
                @click="openReceipt(inv)"
              >
                <td class="py-2.5 pr-4 text-slate-600 dark:text-slate-300">{{ formatDate(inv.created_at) }}</td>
                <td class="py-2.5 pr-4 text-slate-700 dark:text-slate-200">{{ invoiceLabel(inv) }}</td>
                <td class="py-2.5 pr-4 font-medium text-slate-900 dark:text-slate-100">{{ formatAmount(invoiceAmount(inv), inv.currency) }}</td>
                <td class="py-2.5">
                  <div class="flex items-center gap-1.5">
                    <span class="rounded-full px-2 py-0.5 text-xs font-semibold capitalize" :class="invoiceStatusClass(inv)">
                      {{ invoiceStatusLabel(inv) }}
                    </span>
                    <span v-if="inv._sandbox" class="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-semibold text-violet-700">
                      Sandbox
                    </span>
                    <svg class="ml-auto h-3.5 w-3.5 shrink-0 text-slate-400 dark:text-slate-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                    </svg>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

    </div>
  </AppShell>
</template>

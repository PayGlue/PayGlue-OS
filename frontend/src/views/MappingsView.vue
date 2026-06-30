// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { listMappings } from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { ProductMapping } from '../types/api'

const session = useSessionStore()
const mappings = ref<ProductMapping[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

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
    <div class="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <div class="mb-6">
        <h1 class="text-xl font-semibold text-slate-900">Product Mapping</h1>
        <p class="mt-1 text-sm text-slate-500">Ghost actions assigned to each product. Edit them in the Button, Paywall, or Pricing Table editors.</p>
      </div>

      <div v-if="loading" class="text-sm text-slate-400">Loading...</div>
      <div v-else-if="error" class="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</div>
      <div v-else-if="mappings.length === 0" class="rounded-lg border border-slate-200 bg-white px-6 py-10 text-center">
        <p class="text-sm text-slate-500">No mappings configured yet.</p>
        <p class="mt-1 text-xs text-slate-400">Link a product in the Buy Button, Paywall, or Pricing Table editor to create a mapping.</p>
      </div>

      <div v-else class="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table class="w-full text-sm">
          <thead class="border-b border-slate-100 bg-slate-50">
            <tr>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Provider</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Product ID</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Used in</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Trigger</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Newsletter</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Welcome email</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Status</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="m in mappings" :key="m.id" class="hover:bg-slate-50">
              <td class="px-4 py-3 capitalize text-slate-700">{{ m.payment_provider }}</td>
              <td class="px-4 py-3 font-mono text-xs text-slate-500">{{ m.external_product_id }}</td>
              <td class="px-4 py-3 text-slate-700">
                <span v-if="sourceLabel(m)" class="text-sm text-slate-700">{{ sourceLabel(m) }}</span>
                <span v-else class="text-xs text-slate-400">-</span>
              </td>
              <td class="px-4 py-3 text-slate-700">{{ eventLabel(m.event_type) }}</td>
              <td class="px-4 py-3 text-slate-700">
                {{ (m.metadata as any)?.ghost_subscribed === false ? 'No' : 'Yes' }}
              </td>
              <td class="px-4 py-3 text-slate-700">
                {{ emailLabel((m.metadata as any)?.ghost_email_type) }}
              </td>
              <td class="px-4 py-3">
                <span
                  class="rounded-full px-2 py-0.5 text-[11px] font-medium"
                  :class="m.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'"
                >{{ m.is_active ? 'Active' : 'Inactive' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </AppShell>
</template>

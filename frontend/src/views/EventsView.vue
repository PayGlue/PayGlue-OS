// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { listAuditEvents, listWebhookEvents, replayWebhookEvent } from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { AuditEvent, WebhookEvent } from '../types/api'

const session = useSessionStore()
const webhookEvents = ref<WebhookEvent[]>([])
const auditEvents = ref<AuditEvent[]>([])
const loading = ref(false)
const auditLoading = ref(false)
const replaying = ref<Record<number, boolean>>({})
const errorMessage = ref<string | null>(null)
const expandedIds = ref<Set<number>>(new Set())

const auditFilters = reactive({
  event_type: '',
  target_type: '',
  created_at_from: '',
  created_at_to: '',
})

const canReplay = computed(() => {
  const role = session.activeMembership?.role
  return role === 'owner' || role === 'admin'
})

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) throw new Error('Tenant context is missing.')
  return { tenantSlug: session.activeTenantSlug, token: session.idToken }
}

const loadEvents = async () => {
  loading.value = true
  errorMessage.value = null
  try {
    const { tenantSlug, token } = context()
    webhookEvents.value = await listWebhookEvents(tenantSlug, token)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to load events.'
  } finally {
    loading.value = false
  }
}

const buildAuditFilterPayload = () => {
  const payload: Record<string, string> = {}
  if (auditFilters.event_type.trim()) payload.event_type = auditFilters.event_type.trim()
  if (auditFilters.target_type.trim()) payload.target_type = auditFilters.target_type.trim()
  if (auditFilters.created_at_from) payload.created_at_from = new Date(auditFilters.created_at_from).toISOString()
  if (auditFilters.created_at_to) payload.created_at_to = new Date(auditFilters.created_at_to).toISOString()
  return payload
}

const loadAudit = async () => {
  auditLoading.value = true
  errorMessage.value = null
  try {
    const { tenantSlug, token } = context()
    auditEvents.value = await listAuditEvents(tenantSlug, token, buildAuditFilterPayload())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to load audit events.'
  } finally {
    auditLoading.value = false
  }
}

const canReplayEvent = (event: WebhookEvent) => {
  if (!canReplay.value) return false
  return event.status === 'failed' || event.status === 'dead_letter' || event.status === 'skipped'
}

const replay = async (event: WebhookEvent) => {
  if (!canReplayEvent(event)) return
  replaying.value[event.id] = true
  errorMessage.value = null
  try {
    const { tenantSlug, token } = context()
    await replayWebhookEvent(tenantSlug, token, event.id)
    await loadEvents()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to replay event.'
  } finally {
    replaying.value[event.id] = false
  }
}

const toggleExpand = (id: number) => {
  if (expandedIds.value.has(id)) expandedIds.value.delete(id)
  else expandedIds.value.add(id)
}

type StatusFilter = 'all' | 'processed' | 'failed' | 'skipped'
const statusFilter = ref<StatusFilter>('all')

const filteredWebhookEvents = computed(() => {
  if (statusFilter.value === 'processed') return webhookEvents.value.filter(e => e.status === 'processed')
  if (statusFilter.value === 'failed') return webhookEvents.value.filter(e => e.status === 'failed' || e.status === 'dead_letter')
  if (statusFilter.value === 'skipped') return webhookEvents.value.filter(e => e.status === 'skipped')
  return webhookEvents.value
})

const statusColors: Record<string, string> = {
  processed: 'bg-emerald-100 text-emerald-800',
  skipped: 'bg-slate-100 text-slate-500',
  processing: 'bg-blue-100 text-blue-800',
  received: 'bg-slate-100 text-slate-700',
  failed: 'bg-rose-100 text-rose-800',
  dead_letter: 'bg-red-200 text-red-900',
}

const formatTs = (ts: string) => {
  try { return new Date(ts).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'medium' }) }
  catch { return ts }
}

const eventType = (event: WebhookEvent): string => {
  const snap = event.payload_snapshot as Record<string, unknown> | null
  return (snap?.type as string) ?? (snap?.event as string) ?? ''
}

const customerEmail = (event: WebhookEvent): string => {
  const snap = event.payload_snapshot as Record<string, unknown> | null
  if (!snap) return ''
  const data = snap.data as Record<string, unknown> | undefined
  if (!data) return ''
  const order = (data.order ?? data.subscription) as Record<string, unknown> | undefined
  const customer = order?.customer as Record<string, unknown> | undefined
  return (customer?.email as string) ?? ''
}

onMounted(async () => {
  await Promise.all([loadEvents(), loadAudit()])
})
</script>

<template>
  <AppShell>
    <div class="space-y-6">

      <!-- Webhook Events -->
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h1 class="text-xl font-semibold text-slate-900">Webhook events</h1>
            <p class="mt-1 text-sm text-slate-600">Inbound delivery log. Click any row for full payload and error details.</p>
          </div>
          <button type="button" class="shrink-0 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50" @click="loadEvents">Refresh</button>
        </div>

        <p v-if="!canReplay" class="mt-3 text-xs text-amber-700">Your role can inspect events but cannot trigger replays.</p>
        <p v-if="errorMessage" class="mt-3 text-sm text-rose-700">{{ errorMessage }}</p>

        <!-- Status filter -->
        <div class="mt-4 flex flex-wrap gap-1.5 items-center">
          <button
            v-for="f in ([['all', 'All'], ['processed', 'Processed'], ['failed', 'Failed'], ['skipped', 'Skipped']] as [StatusFilter, string][])"
            :key="f[0]"
            type="button"
            class="rounded-full px-3 py-1 text-xs font-medium border transition-colors"
            :class="statusFilter === f[0] ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-600 border-slate-300 hover:bg-slate-50'"
            @click="statusFilter = f[0]"
          >
            {{ f[1] }}
            <span class="ml-1 opacity-60">
              <template v-if="f[0] === 'all'">{{ webhookEvents.length }}</template>
              <template v-else-if="f[0] === 'processed'">{{ webhookEvents.filter(e => e.status === 'processed').length }}</template>
              <template v-else-if="f[0] === 'failed'">{{ webhookEvents.filter(e => e.status === 'failed' || e.status === 'dead_letter').length }}</template>
              <template v-else-if="f[0] === 'skipped'">{{ webhookEvents.filter(e => e.status === 'skipped').length }}</template>
            </span>
          </button>
          <span v-if="statusFilter === 'skipped'" class="text-xs text-slate-400 ml-1">These event types are not needed by PayGlue and are silently acknowledged.</span>
        </div>

        <p v-if="loading" class="mt-4 text-sm text-slate-500">Loading...</p>
        <div v-else-if="filteredWebhookEvents.length === 0" class="mt-4 rounded-xl border border-dashed border-slate-200 py-8 text-center text-sm text-slate-400">
          {{ webhookEvents.length === 0 ? 'No events yet. Events appear here once Polar sends a webhook.' : 'No events match this filter.' }}
        </div>
        <ul v-else class="mt-4 space-y-2">
          <li
            v-for="event in filteredWebhookEvents"
            :key="event.id"
            class="rounded-xl border overflow-hidden"
            :class="event.status === 'failed' || event.status === 'dead_letter' ? 'border-rose-200' : 'border-slate-200'"
          >
            <!-- Header row (always visible, clickable) -->
            <button
              type="button"
              class="w-full flex flex-wrap items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 transition-colors"
              @click="toggleExpand(event.id)"
            >
              <!-- Status badge -->
              <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold" :class="statusColors[event.status] ?? 'bg-slate-100 text-slate-700'">
                {{ event.status }}
              </span>

              <!-- Provider + event type -->
              <span class="text-sm font-medium text-slate-900">{{ event.provider }}<span v-if="eventType(event)" class="text-slate-500"> · {{ eventType(event) }}</span></span>

              <!-- Customer email if available -->
              <span v-if="customerEmail(event)" class="text-xs text-slate-500 font-mono">{{ customerEmail(event) }}</span>

              <span class="ml-auto flex items-center gap-3 text-xs text-slate-400 shrink-0">
                <span>{{ formatTs(event.created_at) }}</span>
                <span>{{ event.attempts }}x</span>
                <!-- chevron -->
                <svg class="h-4 w-4 transition-transform" :class="expandedIds.has(event.id) ? 'rotate-180' : ''" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
                </svg>
              </span>
            </button>

            <!-- Expanded detail -->
            <div v-if="expandedIds.has(event.id)" class="border-t border-slate-100 bg-slate-50 px-4 py-4 space-y-4">

              <!-- Error message (prominent) -->
              <div v-if="event.last_error" class="rounded-lg border border-rose-200 bg-rose-50 px-3 py-3">
                <p class="text-xs font-semibold uppercase tracking-wide text-rose-600 mb-1">Error</p>
                <pre class="whitespace-pre-wrap break-all font-mono text-xs text-rose-800">{{ event.last_error }}</pre>
              </div>

              <!-- Replay button -->
              <div v-if="canReplayEvent(event)">
                <button
                  type="button"
                  class="rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                  :disabled="replaying[event.id]"
                  @click.stop="replay(event)"
                >
                  {{ replaying[event.id] ? 'Replaying...' : 'Replay event' }}
                </button>
              </div>

              <!-- Meta grid -->
              <div class="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
                <div><span class="text-slate-400">Event ID</span> <span class="font-mono text-slate-700">{{ event.id }}</span></div>
                <div><span class="text-slate-400">Attempts</span> <span class="text-slate-700">{{ event.attempts }}</span></div>
                <div v-if="event.next_attempt_at"><span class="text-slate-400">Next retry</span> <span class="text-slate-700">{{ formatTs(event.next_attempt_at) }}</span></div>
                <div v-if="event.dead_lettered_at"><span class="text-slate-400">Dead-lettered</span> <span class="text-slate-700">{{ formatTs(event.dead_lettered_at) }}</span></div>
                <div><span class="text-slate-400">Received</span> <span class="text-slate-700">{{ formatTs(event.created_at) }}</span></div>
                <div v-if="event.updated_at !== event.created_at"><span class="text-slate-400">Updated</span> <span class="text-slate-700">{{ formatTs(event.updated_at) }}</span></div>
              </div>

              <!-- Payload snapshot -->
              <div>
                <p class="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1">Payload</p>
                <pre class="max-h-72 overflow-auto rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-700 leading-relaxed">{{ JSON.stringify(event.payload_snapshot, null, 2) }}</pre>
              </div>
            </div>
          </li>
        </ul>
      </section>

      <!-- Audit Events -->
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 class="text-base font-semibold text-slate-900">Audit log</h2>
        <p class="mt-1 text-sm text-slate-600">Configuration changes and team activity.</p>

        <form class="mt-4 grid gap-3 md:grid-cols-4" @submit.prevent="loadAudit">
          <label class="text-sm text-slate-700">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Event type</span>
            <input v-model="auditFilters.event_type" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label class="text-sm text-slate-700">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Target type</span>
            <input v-model="auditFilters.target_type" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label class="text-sm text-slate-700">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">From</span>
            <input v-model="auditFilters.created_at_from" type="datetime-local" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label class="text-sm text-slate-700">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">To</span>
            <input v-model="auditFilters.created_at_to" type="datetime-local" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <button type="submit" class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50 md:col-span-4 md:justify-self-start" :disabled="auditLoading">
            {{ auditLoading ? 'Loading...' : 'Apply filters' }}
          </button>
        </form>

        <ul v-if="!auditLoading && auditEvents.length" class="mt-4 space-y-2">
          <li v-for="event in auditEvents" :key="event.id" class="rounded-lg border border-slate-200 px-3 py-2.5 text-sm">
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-slate-900">{{ event.event_type }}</span>
              <span class="text-xs text-slate-400 shrink-0">{{ formatTs(event.created_at) }}</span>
            </div>
            <p class="mt-0.5 text-xs text-slate-500">{{ event.target_type }}<span v-if="event.target_id"> · {{ event.target_id }}</span></p>
          </li>
        </ul>
        <p v-else-if="!auditLoading" class="mt-4 text-sm text-slate-500">No audit events found.</p>
      </section>

    </div>
  </AppShell>
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { PageHeader, UiCard, UiButton } from '../components/ui'
import { listAuditEvents, listWebhookEvents, replayWebhookEvent } from '../lib/api'
import { buildEventsLogMarkdown } from '../lib/exportEventsLog'
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
const providerFilter = ref<string>('all')
const eventTypeQuery = ref('')

const availableProviders = computed(() => {
  return Array.from(new Set(webhookEvents.value.map(e => e.provider))).sort()
})

const filteredWebhookEvents = computed(() => {
  let events = webhookEvents.value
  if (statusFilter.value === 'processed') events = events.filter(e => e.status === 'processed')
  else if (statusFilter.value === 'failed') events = events.filter(e => e.status === 'failed' || e.status === 'dead_letter')
  else if (statusFilter.value === 'skipped') events = events.filter(e => e.status === 'skipped')

  if (providerFilter.value !== 'all') events = events.filter(e => e.provider === providerFilter.value)

  const query = eventTypeQuery.value.trim().toLowerCase()
  if (query) {
    events = events.filter(e => {
      if (eventType(e).toLowerCase().includes(query)) return true
      try {
        return JSON.stringify(e.payload_snapshot ?? '').toLowerCase().includes(query)
      } catch {
        return false
      }
    })
  }

  return events
})

const statusColors: Record<string, string> = {
  processed: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300',
  skipped: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
  processing: 'bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-300',
  received: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  failed: 'bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-300',
  dead_letter: 'bg-red-200 text-red-900 dark:bg-red-500/20 dark:text-red-300',
}

const formatTs = (ts: string) => {
  try { return new Date(ts).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'medium' }) }
  catch { return ts }
}

const eventType = (event: WebhookEvent): string => {
  const snap = event.payload_snapshot as Record<string, unknown> | null
  if (!snap) return ''
  if (event.provider === 'lemonsqueezy') {
    const meta = snap.meta as Record<string, unknown> | undefined
    return (meta?.event_name as string) ?? ''
  }
  // Polar/PayPal/Paddle all carry the raw event name at the top level, just
  // under different keys -- Gumroad has no explicit type field at all.
  return (snap.type as string) ?? (snap.event_type as string) ?? (snap.event as string) ?? ''
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

const logCopied = ref(false)

const copyEventsLog = async () => {
  const filterParts: string[] = []
  if (statusFilter.value !== 'all') filterParts.push(`status=${statusFilter.value}`)
  if (providerFilter.value !== 'all') filterParts.push(`provider=${providerFilter.value}`)
  if (eventTypeQuery.value.trim()) filterParts.push(`search="${eventTypeQuery.value.trim()}"`)

  const markdown = buildEventsLogMarkdown(filteredWebhookEvents.value, {
    tenantSlug: session.activeTenantSlug ?? '',
    filterSummary: filterParts.join(', '),
  })
  try {
    await navigator.clipboard.writeText(markdown)
    logCopied.value = true
    setTimeout(() => { logCopied.value = false }, 2000)
  } catch {
    // clipboard unavailable
  }
}

onMounted(async () => {
  await Promise.all([loadEvents(), loadAudit()])
})
</script>

<template>
  <AppShell>
    <div class="space-y-5">
      <PageHeader title="Webhook events" description="Inbound delivery log. Click any row for full payload and error details.">
        <template #actions>
          <UiButton variant="default" size="sm" :disabled="filteredWebhookEvents.length === 0" @click="copyEventsLog">
            {{ logCopied ? 'Copied!' : 'Copy log' }}
          </UiButton>
          <UiButton variant="default" size="sm" @click="loadEvents">Refresh</UiButton>
        </template>
      </PageHeader>

      <!-- Webhook Events -->
      <UiCard>
        <p class="-mt-1 text-xs text-slate-400 dark:text-slate-500">For privacy (GDPR), events older than 90 days are deleted automatically.</p>
        <p v-if="!canReplay" class="mt-3 text-xs text-amber-600 dark:text-amber-400">Your role can inspect events but cannot trigger replays.</p>
        <p v-if="errorMessage" class="mt-3 text-sm text-rose-600 dark:text-rose-400">{{ errorMessage }}</p>

        <!-- Status filter -->
        <div class="mt-4 flex flex-wrap items-center gap-1.5">
          <button
            v-for="f in ([['all', 'All'], ['processed', 'Processed'], ['failed', 'Failed'], ['skipped', 'Skipped']] as [StatusFilter, string][])"
            :key="f[0]"
            type="button"
            class="rounded-full border px-3 py-1 text-xs font-medium transition-colors"
            :class="statusFilter === f[0] ? 'border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900' : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800'"
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
          <span v-if="statusFilter === 'skipped'" class="ml-1 text-xs text-slate-400 dark:text-slate-500">These event types are not needed by PayGlue and are silently acknowledged.</span>
        </div>

        <!-- Provider + event type filter -->
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <select v-model="providerFilter" class="pg-input w-auto text-xs">
            <option value="all">All providers</option>
            <option v-for="p in availableProviders" :key="p" :value="p">{{ p }}</option>
          </select>
          <input
            v-model="eventTypeQuery"
            type="text"
            placeholder="Search event type or payload, e.g. transaction.completed or a product ID"
            class="pg-input w-72 max-w-full text-xs"
          />
          <button
            v-if="providerFilter !== 'all' || eventTypeQuery"
            type="button"
            class="text-xs text-slate-500 underline hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            @click="providerFilter = 'all'; eventTypeQuery = ''"
          >
            Clear
          </button>
        </div>

        <p v-if="loading" class="mt-4 text-sm text-slate-500 dark:text-slate-400">Loading...</p>
        <div v-else-if="filteredWebhookEvents.length === 0" class="mt-4 rounded-xl border border-dashed border-slate-200 py-8 text-center text-sm text-slate-400 dark:border-slate-700 dark:text-slate-500">
          {{ webhookEvents.length === 0 ? 'No events yet. Events appear here once a provider sends a webhook.' : 'No events match this filter.' }}
        </div>
        <ul v-else class="mt-4 space-y-2">
          <li
            v-for="event in filteredWebhookEvents"
            :key="event.id"
            class="overflow-hidden rounded-xl border"
            :class="event.status === 'failed' || event.status === 'dead_letter' ? 'border-rose-200 dark:border-rose-500/30' : 'border-slate-200 dark:border-slate-800'"
          >
            <!-- Header row (always visible, clickable) -->
            <button
              type="button"
              class="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40"
              @click="toggleExpand(event.id)"
            >
              <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold" :class="statusColors[event.status] ?? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'">
                {{ event.status }}
              </span>
              <span class="text-sm font-medium text-slate-900 dark:text-slate-100">{{ event.provider }}<span v-if="eventType(event)" class="text-slate-500 dark:text-slate-400"> · {{ eventType(event) }}</span></span>
              <span v-if="customerEmail(event)" class="font-mono text-xs text-slate-500 dark:text-slate-400">{{ customerEmail(event) }}</span>
              <span class="ml-auto flex shrink-0 items-center gap-3 text-xs text-slate-400 dark:text-slate-500">
                <span>{{ formatTs(event.created_at) }}</span>
                <span>{{ event.attempts }}x</span>
                <svg class="h-4 w-4 transition-transform" :class="expandedIds.has(event.id) ? 'rotate-180' : ''" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
                </svg>
              </span>
            </button>

            <!-- Expanded detail -->
            <div v-if="expandedIds.has(event.id)" class="space-y-4 border-t border-slate-100 bg-slate-50 px-4 py-4 dark:border-slate-800 dark:bg-slate-800/40">
              <div v-if="event.last_error" class="rounded-lg border border-rose-200 bg-rose-50 px-3 py-3 dark:border-rose-500/30 dark:bg-rose-500/10">
                <p class="mb-1 text-xs font-semibold uppercase tracking-wide text-rose-600 dark:text-rose-400">Error</p>
                <pre class="whitespace-pre-wrap break-all font-mono text-xs text-rose-800 dark:text-rose-300">{{ event.last_error }}</pre>
              </div>

              <div v-if="canReplayEvent(event)">
                <UiButton variant="danger" size="sm" :disabled="replaying[event.id]" @click.stop="replay(event)">
                  {{ replaying[event.id] ? 'Replaying...' : 'Replay event' }}
                </UiButton>
              </div>

              <div class="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
                <div><span class="text-slate-400 dark:text-slate-500">Event ID</span> <span class="font-mono text-slate-700 dark:text-slate-300">{{ event.id }}</span></div>
                <div><span class="text-slate-400 dark:text-slate-500">Attempts</span> <span class="text-slate-700 dark:text-slate-300">{{ event.attempts }}</span></div>
                <div v-if="event.next_attempt_at"><span class="text-slate-400 dark:text-slate-500">Next retry</span> <span class="text-slate-700 dark:text-slate-300">{{ formatTs(event.next_attempt_at) }}</span></div>
                <div v-if="event.dead_lettered_at"><span class="text-slate-400 dark:text-slate-500">Dead-lettered</span> <span class="text-slate-700 dark:text-slate-300">{{ formatTs(event.dead_lettered_at) }}</span></div>
                <div><span class="text-slate-400 dark:text-slate-500">Received</span> <span class="text-slate-700 dark:text-slate-300">{{ formatTs(event.created_at) }}</span></div>
                <div v-if="event.updated_at !== event.created_at"><span class="text-slate-400 dark:text-slate-500">Updated</span> <span class="text-slate-700 dark:text-slate-300">{{ formatTs(event.updated_at) }}</span></div>
              </div>

              <div>
                <p class="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">Payload</p>
                <pre class="max-h-72 overflow-auto rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs leading-relaxed text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300">{{ JSON.stringify(event.payload_snapshot, null, 2) }}</pre>
              </div>
            </div>
          </li>
        </ul>
      </UiCard>

      <!-- Audit Events -->
      <UiCard title="Audit log" description="Configuration changes and team activity.">
        <form class="grid gap-3 md:grid-cols-4" @submit.prevent="loadAudit">
          <label>
            <span class="mb-1 block text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Event type</span>
            <input v-model="auditFilters.event_type" class="pg-input" />
          </label>
          <label>
            <span class="mb-1 block text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">Target type</span>
            <input v-model="auditFilters.target_type" class="pg-input" />
          </label>
          <label>
            <span class="mb-1 block text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">From</span>
            <input v-model="auditFilters.created_at_from" type="datetime-local" class="pg-input" />
          </label>
          <label>
            <span class="mb-1 block text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">To</span>
            <input v-model="auditFilters.created_at_to" type="datetime-local" class="pg-input" />
          </label>
          <div class="md:col-span-4">
            <UiButton type="submit" variant="primary" :disabled="auditLoading">
              {{ auditLoading ? 'Loading...' : 'Apply filters' }}
            </UiButton>
          </div>
        </form>

        <ul v-if="!auditLoading && auditEvents.length" class="mt-4 space-y-2">
          <li v-for="event in auditEvents" :key="event.id" class="rounded-lg border border-slate-200 px-3 py-2.5 text-sm dark:border-slate-800">
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-slate-900 dark:text-slate-100">{{ event.event_type }}</span>
              <span class="shrink-0 text-xs text-slate-400 dark:text-slate-500">{{ formatTs(event.created_at) }}</span>
            </div>
            <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{{ event.target_type }}<span v-if="event.target_id"> · {{ event.target_id }}</span></p>
          </li>
        </ul>
        <p v-else-if="!auditLoading" class="mt-4 text-sm text-slate-500 dark:text-slate-400">No audit events found.</p>
      </UiCard>
    </div>
  </AppShell>
</template>

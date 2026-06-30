// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { ApiHttpError, getIntegrationConfig, runIntegrationHealthCheck, setIntegrationCredentials, updateIntegrationConfig } from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { IntegrationConfig, IntegrationHealthStatus } from '../types/api'

const DOCS_URL = 'https://docs.payglue.io/setup/paypal'

const session = useSessionStore()
const loading = ref(false)
const errorMessage = ref<string | null>(null)
const saving = ref(false)
const saved = ref(false)
const healthChecking = ref(false)
const latestHealth = ref<IntegrationHealthStatus | undefined>()

const config = reactive<IntegrationConfig>({
  provider_key: 'payment',
  enabled: false,
  provider_type: 'paypal',
  metadata: {},
})

const form = reactive({ clientId: '', clientSecret: '', webhookId: '' })
const editingClientId = ref(false)
const editingClientSecret = ref(false)
const editingWebhookId = ref(false)
const hasClientId = ref(false)
const hasClientSecret = ref(false)
const hasWebhookId = ref(false)

const canWrite = computed(() => {
  const r = session.activeMembership?.role
  return r === 'owner' || r === 'admin'
})

const webhookUrl = computed(() =>
  `https://api.payglue.io/webhooks/paypal?tenant=${session.activeTenantSlug}`
)

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) throw new ApiHttpError('Missing context.', 400)
  return { tenantSlug: session.activeTenantSlug, idToken: session.idToken }
}

const copyWebhookUrl = async () => { await navigator.clipboard.writeText(webhookUrl.value) }

const load = async () => {
  loading.value = true
  try {
    const { tenantSlug, idToken } = context()
    const c = await getIntegrationConfig(tenantSlug, idToken, 'payment')
    if (c.provider_type === 'paypal') {
      Object.assign(config, c)
      const h = c.metadata.health
      if (h && typeof (h as any).ok === 'boolean') latestHealth.value = h as IntegrationHealthStatus
      const maskedKeys: string[] = (c.metadata as any)?.credential_ref?.masked_keys ?? []
      hasClientId.value = maskedKeys.includes('client_id')
      hasClientSecret.value = maskedKeys.includes('client_secret')
      hasWebhookId.value = maskedKeys.includes('webhook_id')
    }
  } catch (e) {
    if (e instanceof ApiHttpError && e.status === 404) return
    errorMessage.value = e instanceof Error ? e.message : 'Unable to load.'
  } finally {
    loading.value = false
  }
}

const save = async () => {
  if (!canWrite.value) return
  saving.value = true
  errorMessage.value = null
  try {
    const clientId = form.clientId.trim()
    const clientSecret = form.clientSecret.trim()
    const webhookId = form.webhookId.trim()
    const { tenantSlug, idToken } = context()
    await updateIntegrationConfig(tenantSlug, idToken, 'payment', {
      enabled: true,
      provider_type: 'paypal',
      metadata: { ...(config.metadata ?? {}) },
    })
    const creds: Record<string, string> = { sandbox: 'false' }
    if (clientId) creds.client_id = clientId
    if (clientSecret) creds.client_secret = clientSecret
    if (webhookId) creds.webhook_id = webhookId
    const result = await setIntegrationCredentials(tenantSlug, idToken, 'payment', creds)
    const maskedKeys: string[] = (result as any)?.credential_ref?.masked_keys ?? []
    hasClientId.value = maskedKeys.includes('client_id')
    hasClientSecret.value = maskedKeys.includes('client_secret')
    hasWebhookId.value = maskedKeys.includes('webhook_id')
    config.enabled = true
    form.clientId = ''
    form.clientSecret = ''
    form.webhookId = ''
    editingClientId.value = false
    editingClientSecret.value = false
    editingWebhookId.value = false
    saved.value = true
    setTimeout(() => { saved.value = false }, 3000)
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Unable to save.'
  } finally {
    saving.value = false
  }
}

const runHealthCheck = async () => {
  if (!canWrite.value) return
  healthChecking.value = true
  errorMessage.value = null
  try {
    const { tenantSlug, idToken } = context()
    if (!config.provider_key) {
      await updateIntegrationConfig(tenantSlug, idToken, 'payment', { enabled: true, provider_type: 'paypal', metadata: {} })
    }
    latestHealth.value = await runIntegrationHealthCheck(tenantSlug, idToken, 'payment')
    setTimeout(() => { latestHealth.value = undefined }, 5000)
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Health check failed.'
  } finally {
    healthChecking.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <div class="space-y-4">
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h1 class="text-lg font-semibold text-slate-900">PayPal connection</h1>
        <p class="mt-0.5 text-sm text-slate-500">Connect PayPal webhooks to automatically sync member access on subscription and payment events.</p>
        <p v-if="!canWrite" class="mt-2 text-xs text-amber-700">Your role can view but cannot modify this configuration.</p>
        <p v-if="errorMessage" class="mt-2 text-sm text-rose-700">{{ errorMessage }}</p>
      </section>

      <p v-if="loading" class="text-sm text-slate-500 px-1">Loading...</p>

      <section v-if="!loading" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="grid gap-6 lg:grid-cols-2">
          <!-- Left: form -->
          <div class="space-y-3">
            <div>
              <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Webhook URL</span>
              <div class="flex gap-2">
                <input :value="webhookUrl" readonly class="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-xs text-slate-700" />
                <button type="button" class="shrink-0 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50" @click="copyWebhookUrl">Copy</button>
              </div>
            </div>

            <div>
              <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Client ID</span>
              <div v-if="hasClientId && !editingClientId" class="flex items-center gap-2">
                <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-sm tracking-widest text-slate-400">••••••••••••</div>
                <button v-if="canWrite" type="button" class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" @click="editingClientId = true; form.clientId = ''">Update</button>
              </div>
              <input v-else v-model="form.clientId" type="password" placeholder="Your PayPal REST API Client ID" autocomplete="off" :disabled="!canWrite" class="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-sm" />
            </div>

            <div>
              <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Client Secret</span>
              <div v-if="hasClientSecret && !editingClientSecret" class="flex items-center gap-2">
                <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-sm tracking-widest text-slate-400">••••••••••••</div>
                <button v-if="canWrite" type="button" class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" @click="editingClientSecret = true; form.clientSecret = ''">Update</button>
              </div>
              <input v-else v-model="form.clientSecret" type="password" placeholder="Your PayPal REST API Client Secret" autocomplete="off" :disabled="!canWrite" class="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-sm" />
            </div>

            <div>
              <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Webhook ID</span>
              <div v-if="hasWebhookId && !editingWebhookId" class="flex items-center gap-2">
                <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-sm tracking-widest text-slate-400">••••••••••••</div>
                <button v-if="canWrite" type="button" class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" @click="editingWebhookId = true; form.webhookId = ''">Update</button>
              </div>
              <input v-else v-model="form.webhookId" type="text" placeholder="Webhook ID from PayPal Developer dashboard" autocomplete="off" :disabled="!canWrite" class="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-sm" />
              <p class="mt-1 text-xs text-slate-400">PayPal uses this to verify webhook authenticity. You find it after creating the webhook in the Developer dashboard.</p>
            </div>

            <div class="flex items-center gap-1.5 text-xs">
              <span v-if="config.enabled" class="inline-block h-2 w-2 rounded-full bg-emerald-500"></span>
              <span v-if="config.enabled" class="font-medium text-emerald-700">Connected</span>
              <span v-else class="inline-block h-2 w-2 rounded-full bg-rose-500"></span>
              <span v-if="!config.enabled" class="font-medium text-rose-600">Not connected — Client ID and Secret are required</span>
            </div>

            <div class="flex flex-wrap gap-2 pt-1">
              <button
                v-if="!config.enabled || editingClientId || editingClientSecret || editingWebhookId || form.clientId || form.clientSecret || form.webhookId"
                type="button"
                class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40"
                :disabled="!canWrite || saving"
                @click="save"
              >
                {{ saving ? 'Saving...' : saved ? 'Saved!' : 'Save credentials' }}
              </button>
              <button type="button" class="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="!canWrite || healthChecking" @click="runHealthCheck">
                {{ healthChecking ? 'Checking...' : 'Run health check' }}
              </button>
            </div>

            <div v-if="latestHealth" class="rounded-lg border p-3 text-sm" :class="latestHealth.ok ? 'border-emerald-200 bg-emerald-50' : 'border-rose-200 bg-rose-50'">
              <p class="font-semibold" :class="latestHealth.ok ? 'text-emerald-800' : 'text-rose-800'">{{ latestHealth.ok ? 'Connection established' : 'Connection failed' }}</p>
              <p class="mt-0.5 text-xs" :class="latestHealth.ok ? 'text-emerald-700' : 'text-rose-700'">{{ latestHealth.message }}</p>
            </div>
          </div>

          <!-- Right: setup guide -->
          <div class="space-y-2">
            <p class="text-xs font-semibold uppercase tracking-widest text-indigo-600">How to set up</p>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 1</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Open the PayPal Developer dashboard</p>
              <p class="mt-0.5 text-xs text-slate-500">Go to <strong>developer.paypal.com</strong>, log in with your PayPal business account, and open <strong>Apps &amp; Credentials</strong>.</p>
            </div>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 2</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Create a REST API app</p>
              <p class="mt-0.5 text-xs text-slate-500">Click <strong>Create App</strong>, give it a name (e.g. "PayGlue"), and select <strong>Merchant</strong> as the app type. After creation, copy the <strong>Client ID</strong> and <strong>Client Secret</strong>.</p>
            </div>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 3</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Add a webhook</p>
              <p class="mt-0.5 text-xs text-slate-500">Scroll down to <strong>Webhooks</strong> inside your app and click <strong>Add Webhook</strong>. Paste the Webhook URL from the left. Enable these events:</p>
              <ul class="mt-1.5 space-y-0.5 font-mono text-[11px] text-slate-600">
                <li>BILLING.SUBSCRIPTION.ACTIVATED</li>
                <li>BILLING.SUBSCRIPTION.CANCELLED</li>
                <li>BILLING.SUBSCRIPTION.EXPIRED</li>
                <li>BILLING.SUBSCRIPTION.SUSPENDED</li>
                <li>BILLING.SUBSCRIPTION.UPDATED</li>
                <li>PAYMENT.CAPTURE.COMPLETED</li>
              </ul>
            </div>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 4</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Copy the Webhook ID</p>
              <p class="mt-0.5 text-xs text-slate-500">After saving the webhook, PayPal shows a <strong>Webhook ID</strong>. Copy it and paste it into the field on the left.</p>
            </div>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 5</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Save in PayGlue</p>
              <p class="mt-0.5 text-xs text-slate-500">Enter Client ID, Client Secret, and Webhook ID into the fields on the left, then click <strong>Save credentials</strong>.</p>
            </div>
            <a :href="DOCS_URL" target="_blank" rel="noopener" class="inline-block pt-1 text-xs text-blue-700 hover:underline">Full setup guide →</a>
          </div>
        </div>
      </section>
    </div>
  </AppShell>
</template>

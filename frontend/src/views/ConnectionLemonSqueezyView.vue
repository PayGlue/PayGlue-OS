// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { ApiHttpError, getIntegrationConfig, getLemonSqueezyStores, runIntegrationHealthCheck, setIntegrationCredentials, updateIntegrationConfig } from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { IntegrationConfig, IntegrationHealthStatus } from '../types/api'

const DOCS_URL = 'https://docs.payglue.io/setup/lemon-squeezy'

const session = useSessionStore()
const loading = ref(false)
const errorMessage = ref<string | null>(null)
const saving = ref(false)
const saved = ref(false)
const healthChecking = ref(false)
const latestHealth = ref<IntegrationHealthStatus | undefined>()
const editingSecret = ref(false)

const config = reactive<IntegrationConfig>({
  provider_key: 'payment',
  enabled: false,
  provider_type: 'lemonsqueezy',
  metadata: {},
})

const form = reactive({ webhookSecret: '', apiKey: '' })
const editingApiKey = ref(false)
const hasApiKey = ref(false)

interface LsStore { id: string; name: string; slug: string }
const stores = ref<LsStore[]>([])
const storesLoading = ref(false)
const storesError = ref<string | null>(null)
const selectedStoreId = ref('')

const canWrite = computed(() => {
  const r = session.activeMembership?.role
  return r === 'owner' || r === 'admin'
})

const webhookUrl = computed(() =>
  `https://api.payglue.io/webhooks/lemonsqueezy?tenant=${session.activeTenantSlug}`
)

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) throw new ApiHttpError('Missing context.', 400)
  return { tenantSlug: session.activeTenantSlug, idToken: session.idToken }
}

const copyWebhookUrl = async () => { await navigator.clipboard.writeText(webhookUrl.value) }

const loadStores = async () => {
  if (!session.activeTenantSlug || !session.idToken) return
  storesLoading.value = true
  storesError.value = null
  try {
    const result = await getLemonSqueezyStores(session.activeTenantSlug, session.idToken)
    stores.value = result.stores ?? []
    if (result.selected_store_id) selectedStoreId.value = result.selected_store_id
    else if (result.stores && result.stores.length === 1) selectedStoreId.value = result.stores[0]?.id ?? ''
    if (!stores.value.length) storesError.value = 'No stores found. Check that your API key has access to at least one store.'
  } catch {
    storesError.value = 'Could not load stores. Check your API key and try again.'
  } finally {
    storesLoading.value = false
  }
}

const load = async () => {
  loading.value = true
  try {
    const { tenantSlug, idToken } = context()
    const c = await getIntegrationConfig(tenantSlug, idToken, 'payment')
    if (c.provider_type === 'lemonsqueezy') {
      Object.assign(config, c)
      const h = c.metadata.health
      if (h && typeof (h as any).ok === 'boolean') latestHealth.value = h as IntegrationHealthStatus
      const maskedKeys: string[] = (c.metadata as any)?.credential_ref?.masked_keys ?? []
      hasApiKey.value = maskedKeys.includes('api_key')
      if (hasApiKey.value) loadStores()
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
    const secret = form.webhookSecret.trim()
    const apiKey = form.apiKey.trim()
    if (!secret && !config.enabled) throw new Error('Signing secret is required.')
    const { tenantSlug, idToken } = context()
    await updateIntegrationConfig(tenantSlug, idToken, 'payment', { enabled: true, provider_type: 'lemonsqueezy', metadata: config.metadata ?? {} })
    const creds: Record<string, string> = {}
    if (secret) creds.webhook_secret = secret
    if (apiKey) creds.api_key = apiKey
    if (selectedStoreId.value) creds.store_id = selectedStoreId.value
    if (Object.keys(creds).length > 0) {
      const result = await setIntegrationCredentials(tenantSlug, idToken, 'payment', creds)
      const maskedKeys: string[] = (result as any)?.credential_ref?.masked_keys ?? []
      hasApiKey.value = maskedKeys.includes('api_key')
      if (apiKey || (hasApiKey.value && !stores.value.length)) await loadStores()
    }
    config.enabled = true
    form.webhookSecret = ''
    form.apiKey = ''
    editingSecret.value = false
    editingApiKey.value = false
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
      await updateIntegrationConfig(tenantSlug, idToken, 'payment', { enabled: true, provider_type: 'lemonsqueezy', metadata: {} })
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
        <h1 class="text-lg font-semibold text-slate-900">Lemon Squeezy connection</h1>
        <p class="mt-0.5 text-sm text-slate-500">Connect Lemon Squeezy webhooks to automatically sync member access on payment events.</p>
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
              <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Signing secret</span>
              <div v-if="config.enabled && !editingSecret" class="flex items-center gap-2">
                <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-sm tracking-widest text-slate-400">••••••••••••</div>
                <button v-if="canWrite" type="button" class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" @click="editingSecret = true; form.webhookSecret = ''">Update</button>
              </div>
              <input v-else v-model="form.webhookSecret" type="password" placeholder="Your signing secret (same value as entered in Lemon Squeezy)" autocomplete="off" :disabled="!canWrite" class="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-sm" />
              <p v-if="!config.enabled" class="mt-1 text-xs text-slate-400">You choose this secret yourself — enter the same value here and in Lemon Squeezy.</p>
            </div>

            <div>
              <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">API key</span>
              <div v-if="hasApiKey && !editingApiKey" class="flex items-center gap-2">
                <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-sm tracking-widest text-slate-400">••••••••••••</div>
                <button v-if="canWrite" type="button" class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" @click="editingApiKey = true; form.apiKey = ''">Update</button>
              </div>
              <input v-else v-model="form.apiKey" type="password" placeholder="Your Lemon Squeezy API key (for product fetching)" autocomplete="off" :disabled="!canWrite" class="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-sm" />
              <p class="mt-1 text-xs text-slate-400">Used to load your products in the Paywall, Buy Button, and Pricing Table editors. Find it in Lemon Squeezy under Settings &gt; API. To see test products, use the API key generated while test mode is active in the LS dashboard.</p>
            </div>

            <div v-if="hasApiKey || form.apiKey">
              <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Store</span>
              <p v-if="storesLoading" class="text-xs text-slate-400">Loading stores...</p>
              <template v-else>
                <p v-if="storesError" class="mb-1 text-xs text-amber-600">{{ storesError }}</p>
                <select v-model="selectedStoreId" :disabled="!canWrite"
                  class="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-800 focus:border-indigo-400 focus:outline-none">
                  <option value="">Select your store</option>
                  <option v-for="s in stores" :key="s.id" :value="s.id">{{ s.name }} ({{ s.slug }})</option>
                </select>
              </template>
              <p class="mt-1 text-xs text-slate-400">Limits product fetching to this store. Required if your API key has access to multiple stores.</p>
            </div>

            <div class="flex items-center gap-1.5 text-xs">
              <span v-if="config.enabled" class="inline-block h-2 w-2 rounded-full bg-emerald-500"></span>
              <span v-if="config.enabled" class="font-medium text-emerald-700">Connected</span>
              <span v-else class="inline-block h-2 w-2 rounded-full bg-rose-500"></span>
              <span v-if="!config.enabled" class="font-medium text-rose-600">Not connected — a signing secret is required</span>
            </div>

            <div class="flex flex-wrap gap-2 pt-1">
              <button v-if="!config.enabled || editingSecret || editingApiKey || form.apiKey || form.webhookSecret || selectedStoreId" type="button" class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40" :disabled="!canWrite || saving" @click="save">
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
              <p class="mt-0.5 text-sm font-medium text-slate-800">Open Lemon Squeezy settings</p>
              <p class="mt-0.5 text-xs text-slate-500">In your Lemon Squeezy dashboard, click your store name and go to <strong>Settings</strong>.</p>
            </div>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 2</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Open Webhooks</p>
              <p class="mt-0.5 text-xs text-slate-500">Click <strong>Webhooks</strong> in the left sidebar, then click <strong>+ Add webhook</strong>.</p>
            </div>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 3</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Create a signing secret</p>
              <p class="mt-0.5 text-xs text-slate-500">In the <strong>Signing secret</strong> field in Lemon Squeezy, enter any random string you choose — for example a long password. You will paste the same value into PayGlue in Step 5.</p>
            </div>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 4</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Paste the webhook URL and select events</p>
              <p class="mt-0.5 text-xs text-slate-500">Paste the Webhook URL from the left into <strong>Callback URL</strong>. Then enable these events:</p>
              <ul class="mt-1.5 space-y-0.5 font-mono text-[11px] text-slate-600">
                <li>order_created</li>
                <li>subscription_created</li>
                <li>subscription_updated</li>
                <li>subscription_resumed</li>
                <li>subscription_unpaused</li>
                <li>subscription_payment_success</li>
                <li>subscription_cancelled</li>
                <li>subscription_paused</li>
                <li>subscription_expired</li>
              </ul>
            </div>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 5</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Save in PayGlue</p>
              <p class="mt-0.5 text-xs text-slate-500">Enter the <strong>same signing secret</strong> you chose in Step 3 into the field on the left, then click <strong>Save credentials</strong>.</p>
            </div>
            <a :href="DOCS_URL" target="_blank" rel="noopener" class="inline-block pt-1 text-xs text-blue-700 hover:underline">Full setup guide →</a>
          </div>
        </div>
      </section>
    </div>
  </AppShell>
</template>

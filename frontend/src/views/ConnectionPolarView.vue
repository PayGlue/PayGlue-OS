// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { ApiHttpError, getIntegrationConfig, getPolarProducts, runIntegrationHealthCheck, setIntegrationCredentials, updateIntegrationConfig } from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { IntegrationConfig, IntegrationHealthStatus } from '../types/api'

const DOCS_URL = 'https://docs.payglue.io/setup/polar'

const session = useSessionStore()
const loading = ref(false)
const errorMessage = ref<string | null>(null)
const saving = ref(false)
const saved = ref(false)
const healthChecking = ref(false)
const latestHealth = ref<IntegrationHealthStatus | undefined>()
const editingSecret = ref(false)
const webhookConfirmed = ref(false)

const config = reactive<IntegrationConfig>({
  provider_key: 'payment',
  enabled: false,
  provider_type: 'polar',
  metadata: {},
})

const form = reactive({ webhookSecret: '', accessToken: '' })
const savingToken = ref(false)
const savedToken = ref(false)
const hasStoredToken = ref(false)
const editingToken = ref(false)

const canWrite = computed(() => {
  const r = session.activeMembership?.role
  return r === 'owner' || r === 'admin'
})

const webhookUrl = computed(() =>
  `https://api.payglue.io/webhooks/polar?tenant=${session.activeTenantSlug}`
)

const pendingRenameKey = computed(() =>
  session.activeTenantSlug ? `payglue:pending-rename:${session.activeTenantSlug}` : null
)

const hasPendingRename = ref(false)

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
    Object.assign(config, c)
    const h = c.metadata.health
    if (h && typeof (h as any).ok === 'boolean') latestHealth.value = h as IntegrationHealthStatus
    if (pendingRenameKey.value) {
      hasPendingRename.value = localStorage.getItem(pendingRenameKey.value) === '1'
    }
    try {
      const products = await getPolarProducts(tenantSlug, idToken)
      hasStoredToken.value = products.has_token
    } catch { /* token check is non-critical */ }
  } catch (e) {
    if (e instanceof ApiHttpError && e.status === 404) return
    errorMessage.value = e instanceof Error ? e.message : 'Unable to load.'
  } finally {
    loading.value = false
  }
}

const dismissRenameWarning = () => {
  if (pendingRenameKey.value) localStorage.removeItem(pendingRenameKey.value)
  hasPendingRename.value = false
}

const save = async () => {
  if (!canWrite.value) return
  saving.value = true
  errorMessage.value = null
  try {
    const secret = form.webhookSecret.trim()
    if (!secret) throw new Error('Webhook secret is required.')
    const { tenantSlug, idToken } = context()
    await updateIntegrationConfig(tenantSlug, idToken, 'payment', { enabled: true, provider_type: 'polar', metadata: config.metadata ?? {} })
    const creds: Record<string, string> = { webhook_secret: secret }
    if (form.accessToken.trim()) creds.access_token = form.accessToken.trim()
    await setIntegrationCredentials(tenantSlug, idToken, 'payment', creds)
    config.enabled = true
    form.webhookSecret = ''
    editingSecret.value = false
    saved.value = true
    setTimeout(() => { saved.value = false }, 3000)
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Unable to save.'
  } finally {
    saving.value = false
  }
}

const saveToken = async () => {
  if (!canWrite.value) return
  const token = form.accessToken.trim()
  if (!token) return
  savingToken.value = true
  errorMessage.value = null
  try {
    const { tenantSlug, idToken } = context()
    await setIntegrationCredentials(tenantSlug, idToken, 'payment', { access_token: token })
    form.accessToken = ''
    hasStoredToken.value = true
    editingToken.value = false
    savedToken.value = true
    setTimeout(() => { savedToken.value = false }, 3000)
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Unable to save token.'
  } finally {
    savingToken.value = false
  }
}

const runHealthCheck = async () => {
  if (!canWrite.value) return
  healthChecking.value = true
  errorMessage.value = null
  try {
    const { tenantSlug, idToken } = context()
    if (!config.provider_key) {
      await updateIntegrationConfig(tenantSlug, idToken, 'payment', { enabled: true, provider_type: 'polar', metadata: {} })
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
      <!-- Rename warning banner -->
      <div v-if="hasPendingRename" class="rounded-xl border-2 border-amber-400 bg-amber-50 p-4">
        <div class="flex items-start gap-3">
          <svg class="mt-0.5 h-5 w-5 shrink-0 text-amber-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          <div class="flex-1">
            <p class="font-semibold text-amber-900">Organization renamed — update your webhook URL</p>
            <p class="mt-1 text-sm text-amber-800">
              Your organization slug changed. The webhook URL for Polar has changed. Please update the endpoint URL in your Polar dashboard to:
            </p>
            <code class="mt-2 block rounded bg-amber-100 px-3 py-1.5 text-xs font-mono text-amber-900">{{ webhookUrl }}</code>
            <label class="mt-3 flex items-center gap-2 cursor-pointer">
              <input v-model="webhookConfirmed" type="checkbox" class="h-4 w-4 accent-amber-600" @change="webhookConfirmed && dismissRenameWarning()" />
              <span class="text-sm text-amber-900">I have updated the webhook URL in Polar. Dismiss this warning.</span>
            </label>
          </div>
        </div>
      </div>

      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h1 class="text-lg font-semibold text-slate-900">Polar connection</h1>
        <p class="mt-0.5 text-sm text-slate-500">Connect Polar webhooks to automatically sync member access on payment events.</p>
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
              <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Webhook secret</span>
              <div v-if="config.enabled && !editingSecret" class="flex items-center gap-2">
                <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-sm tracking-widest text-slate-400">••••••••••••</div>
                <button v-if="canWrite" type="button" class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" @click="editingSecret = true; form.webhookSecret = ''">Update</button>
              </div>
              <input v-else v-model="form.webhookSecret" type="password" placeholder="whsec_..." autocomplete="off" :disabled="!canWrite" class="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-sm" />
            </div>

            <!-- Optional: Polar Access Token for product autofetch -->
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3 space-y-2">
              <div>
                <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Polar API token <span class="normal-case font-normal text-slate-400">(optional)</span></span>
                <div v-if="hasStoredToken && !editingToken" class="flex items-center gap-2">
                  <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-sm tracking-widest text-slate-400">••••••••••••</div>
                  <button v-if="canWrite" type="button" class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50" @click="editingToken = true; form.accessToken = ''">Update</button>
                </div>
                <input v-else v-model="form.accessToken" type="password" placeholder="polar_at_..." autocomplete="off" :disabled="!canWrite" class="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-sm" />
              </div>
              <p class="text-xs text-slate-500">
                Needed for product auto-fetch in Mappings. Get it in Polar under <strong>Settings &gt; Preferences &gt; Developers &gt; Access Tokens</strong>. Set expiration to <strong>Never</strong>.
                Enable <strong>products:read</strong>, <strong>checkout_links:read</strong>, and <strong>checkout_links:write</strong>. PayGlue uses these to auto-fetch your products and auto-generate the checkout URL in the Paywall editor — for both production and sandbox. Without these scopes, you will need to paste the checkout URL manually.
                Without this token, you can still add mappings by entering the product ID manually.
              </p>
              <button
                v-if="config.enabled && (!hasStoredToken || editingToken)"
                type="button"
                class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40"
                :disabled="!canWrite || savingToken || !form.accessToken.trim()"
                @click="saveToken"
              >
                {{ savingToken ? 'Saving...' : savedToken ? 'Saved!' : 'Save API token' }}
              </button>
            </div>

            <div class="flex items-center gap-1.5 text-xs">
              <span v-if="config.enabled" class="inline-block h-2 w-2 rounded-full bg-emerald-500"></span>
              <span v-if="config.enabled" class="font-medium text-emerald-700">Connected</span>
              <span v-else class="inline-block h-2 w-2 rounded-full bg-rose-500"></span>
              <span v-if="!config.enabled" class="font-medium text-rose-600">Not connected — a webhook secret is required</span>
            </div>

            <div class="flex flex-wrap gap-2 pt-1">
              <button v-if="!config.enabled || editingSecret" type="button" class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40" :disabled="!canWrite || saving" @click="save">
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
              <p class="mt-0.5 text-sm font-medium text-slate-800">Open Polar settings</p>
              <p class="mt-0.5 text-xs text-slate-500">In your Polar dashboard, go to <strong>Settings</strong> and click <strong>Webhooks</strong> in the sidebar.</p>
            </div>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 2</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Add endpoint</p>
              <p class="mt-0.5 text-xs text-slate-500">Click <strong>+ Add endpoint</strong>. Set format to <strong>Raw</strong>, paste the Webhook URL above. Select only these events (we don't recommend "All events"):</p>
              <ul class="mt-1.5 space-y-0.5 font-mono text-[11px] text-slate-600">
                <li>benefit_grant.created</li>
                <li>benefit_grant.updated</li>
                <li>benefit_grant.revoked</li>
                <li>order.created</li>
                <li>subscription.active</li>
                <li>subscription.canceled</li>
                <li>subscription.revoked</li>
              </ul>
            </div>
            <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 3</p>
              <p class="mt-0.5 text-sm font-medium text-slate-800">Copy the secret</p>
              <p class="mt-0.5 text-xs text-slate-500">After saving, Polar shows a <strong>Webhook secret</strong>. Copy it, paste it into the field above, then click <strong>Save credentials</strong>.</p>
            </div>
            <a :href="DOCS_URL" target="_blank" rel="noopener" class="inline-block pt-1 text-xs text-blue-700 hover:underline">Full setup guide →</a>
          </div>
        </div>
      </section>
    </div>
  </AppShell>
</template>

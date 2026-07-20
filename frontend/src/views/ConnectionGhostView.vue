// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted, reactive, ref, computed, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import { PageHeader, UiCard, UiButton, FormField, ProviderLogo } from '../components/ui'
import { ApiHttpError, getGhostStripeStatus, getIntegrationConfig, runIntegrationHealthCheck, setIntegrationCredentials, updateIntegrationConfig } from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { IntegrationConfig, IntegrationHealthStatus } from '../types/api'

const DOCS_URL = 'https://docs.payglue.io/setup/ghost'

const session = useSessionStore()
const loading = ref(false)
const errorMessage = ref<string | null>(null)
const saving = ref(false)
const saved = ref(false)
const healthChecking = ref(false)
const latestHealth = ref<IntegrationHealthStatus | undefined>()
const stripeStatus = ref<{ connected: boolean; display_name?: string | null; error?: string } | null>(null)
const stripeStatusLoading = ref(false)
const editingCredentials = ref(false)

const config = reactive<IntegrationConfig>({
  provider_key: 'cms',
  enabled: false,
  provider_type: 'ghost',
  metadata: {},
})

const form = reactive({ apiBaseUrl: '', contentApiKey: '', adminApiKey: '' })

const DEV_URL = 'https://dev.example.com'
const DEV_CONTENT = 'acac4d839f6cfa04b907a04cf4deadbeef'
const DEV_ADMIN = '6a3145b0e72c430001fdcd39:f0533b2bdeadbeefdeadbeefdeadbeef'

const isDevMode = computed(() =>
  form.apiBaseUrl === DEV_URL && form.contentApiKey === DEV_CONTENT && form.adminApiKey === DEV_ADMIN,
)

watch(() => [form.apiBaseUrl, form.contentApiKey, form.adminApiKey], ([url, content, admin]) => {
  if ((url ?? '').trim() === 'x' || (content ?? '').trim() === 'x' || (admin ?? '').trim() === 'x') {
    form.apiBaseUrl = DEV_URL
    form.contentApiKey = DEV_CONTENT
    form.adminApiKey = DEV_ADMIN
  }
})

const canWrite = computed(() => {
  const r = session.activeMembership?.role
  return r === 'owner' || r === 'admin'
})

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) throw new ApiHttpError('Missing context.', 400)
  return { tenantSlug: session.activeTenantSlug, idToken: session.idToken }
}

const validateUrl = (v: string) => {
  try { new URL(v) } catch { throw new Error('Ghost URL must be a valid URL.') }
}

const load = async () => {
  loading.value = true
  try {
    const { tenantSlug, idToken } = context()
    const c = await getIntegrationConfig(tenantSlug, idToken, 'cms')
    Object.assign(config, c)
    const h = c.metadata.health
    if (h && typeof (h as any).ok === 'boolean') latestHealth.value = h as IntegrationHealthStatus
    // Read URL from metadata (primary) or localStorage fallback
    if (typeof c.metadata.api_base_url === 'string' && c.metadata.api_base_url) {
      form.apiBaseUrl = c.metadata.api_base_url
    } else {
      const raw = localStorage.getItem(`payglue:ghost:${tenantSlug}`)
      if (raw) {
        try {
          const d = JSON.parse(raw) as { url?: string }
          if (d.url) form.apiBaseUrl = d.url
        } catch { /* ignore */ }
      }
    }
    if (c.enabled) loadStripeStatus(tenantSlug, idToken)
  } catch (e) {
    if (e instanceof ApiHttpError && e.status === 404) return
    errorMessage.value = e instanceof Error ? e.message : 'Unable to load.'
  } finally {
    loading.value = false
  }
}

const loadStripeStatus = async (tenantSlug: string, idToken: string) => {
  stripeStatusLoading.value = true
  try {
    stripeStatus.value = await getGhostStripeStatus(tenantSlug, idToken)
  } catch {
    stripeStatus.value = { connected: false, error: 'request_failed' }
  } finally {
    stripeStatusLoading.value = false
  }
}

const save = async () => {
  if (!canWrite.value) return
  saving.value = true
  errorMessage.value = null
  try {
    const url = form.apiBaseUrl.trim()
    if (!url) throw new Error('Ghost URL is required.')
    if (!isDevMode.value) validateUrl(url)
    const { tenantSlug, idToken } = context()

    // Already connected and not re-entering keys: only update the URL in metadata.
    if (config.enabled && !editingCredentials.value) {
      const newMeta = { ...(config.metadata ?? {}), api_base_url: url }
      await updateIntegrationConfig(tenantSlug, idToken, 'cms', { enabled: true, provider_type: 'ghost', metadata: newMeta })
      Object.assign(config.metadata as Record<string, unknown>, newMeta)
      localStorage.setItem(`payglue:ghost:${tenantSlug}`, JSON.stringify({ url }))
      saved.value = true
      setTimeout(() => { saved.value = false }, 3000)
      return
    }

    const adminKey = form.adminApiKey.trim()
    if (!adminKey) throw new Error('Admin API key is required.')
    if (!adminKey.includes(':')) throw new Error('Admin API key must use format <id>:<secret>.')

    if (isDevMode.value) {
      localStorage.setItem(`payglue:ghost:${tenantSlug}`, JSON.stringify({ url }))
      config.enabled = true
      form.contentApiKey = ''
      form.adminApiKey = ''
      editingCredentials.value = false
      saved.value = true
      setTimeout(() => { saved.value = false }, 3000)
      return
    }
    await updateIntegrationConfig(tenantSlug, idToken, 'cms', { enabled: true, provider_type: 'ghost', metadata: { ...(config.metadata ?? {}), api_base_url: url } })
    const creds: Record<string, string> = { api_base_url: url, admin_api_key: adminKey }
    if (form.contentApiKey.trim()) creds.content_api_key = form.contentApiKey.trim()
    await setIntegrationCredentials(tenantSlug, idToken, 'cms', creds)
    localStorage.setItem(`payglue:ghost:${tenantSlug}`, JSON.stringify({ url }))
    config.enabled = true
    form.contentApiKey = ''
    form.adminApiKey = ''
    editingCredentials.value = false
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
      await updateIntegrationConfig(tenantSlug, idToken, 'cms', { enabled: true, provider_type: 'ghost', metadata: {} })
    }
    latestHealth.value = await runIntegrationHealthCheck(tenantSlug, idToken, 'cms')
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
    <div class="space-y-5">
      <PageHeader title="Ghost CMS" description="Connect your Ghost instance via the Admin API to enable member sync.">
        <template #actions>
          <ProviderLogo provider="ghost" size="md" />
        </template>
      </PageHeader>

      <p v-if="!canWrite" class="text-xs text-amber-600 dark:text-amber-400">Your role can view but cannot modify this configuration.</p>
      <p v-if="errorMessage" class="text-sm text-rose-600 dark:text-rose-400">{{ errorMessage }}</p>

      <p v-if="loading" class="px-1 text-sm text-slate-500 dark:text-slate-400">Loading...</p>

      <div v-if="!loading" class="grid gap-5 lg:grid-cols-3">
        <!-- Left: form -->
        <UiCard class="lg:col-span-2">
          <div class="space-y-4">
            <FormField label="Ghost URL">
              <input v-model="form.apiBaseUrl" type="url" placeholder="https://www.yourblog.com" :disabled="!canWrite" class="pg-input" />
            </FormField>

            <template v-if="config.enabled && !editingCredentials">
              <FormField label="Content API key">
                <div class="pg-input pg-dots">••••••••••••</div>
              </FormField>
              <FormField label="Admin API key">
                <div class="pg-input pg-dots">••••••••••••</div>
              </FormField>
              <UiButton v-if="canWrite" size="sm" variant="default" @click="editingCredentials = true">Update credentials</UiButton>
            </template>

            <template v-else>
              <FormField label="Content API key">
                <input v-model="form.contentApiKey" type="password" placeholder="acac4d839f6cfa04b907a04cf4..." autocomplete="off" :disabled="!canWrite" class="pg-input pg-mono" />
              </FormField>
              <FormField label="Admin API key">
                <input v-model="form.adminApiKey" type="password" placeholder="6a3145b0e72c430001fdcd39:f0533b2b..." autocomplete="off" :disabled="!canWrite" class="pg-input pg-mono" />
              </FormField>
            </template>

            <div class="flex items-center gap-1.5 text-xs">
              <span class="inline-block h-2 w-2 rounded-full" :class="config.enabled ? 'bg-emerald-500' : 'bg-rose-500'"></span>
              <span v-if="config.enabled" class="font-medium text-emerald-600 dark:text-emerald-400">Connected</span>
              <span v-else class="font-medium text-rose-600 dark:text-rose-400">Not connected</span>
            </div>

            <div class="flex flex-wrap gap-2 pt-1">
              <UiButton variant="primary" :disabled="!canWrite || saving" @click="save">
                {{ saving ? 'Saving...' : saved ? 'Saved!' : 'Save credentials' }}
              </UiButton>
              <UiButton variant="default" :disabled="!canWrite || healthChecking" @click="runHealthCheck">
                {{ healthChecking ? 'Checking...' : 'Run health check' }}
              </UiButton>
            </div>

            <div
              v-if="latestHealth"
              class="rounded-xl border p-3 text-sm"
              :class="latestHealth.ok ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-500/30 dark:bg-emerald-500/10' : 'border-rose-200 bg-rose-50 dark:border-rose-500/30 dark:bg-rose-500/10'"
            >
              <p class="font-semibold" :class="latestHealth.ok ? 'text-emerald-800 dark:text-emerald-300' : 'text-rose-800 dark:text-rose-300'">{{ latestHealth.ok ? 'Connection established' : 'Connection failed' }}</p>
              <p class="mt-0.5 text-xs" :class="latestHealth.ok ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'">{{ latestHealth.message }}</p>
            </div>
          </div>
        </UiCard>

        <!-- Right: setup guide -->
        <UiCard title="How to set up" description="3 steps.">
          <div class="space-y-2.5">
            <div class="rounded-xl border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/40">
              <div class="flex items-start gap-2.5">
                <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[11px] font-bold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">1</span>
                <div class="min-w-0">
                  <p class="text-sm font-semibold text-slate-800 dark:text-slate-100">Open Ghost admin</p>
                  <p class="mt-0.5 text-xs leading-relaxed text-slate-500 dark:text-slate-400">In your Ghost dashboard, go to <strong>Settings → Integrations</strong> and click <strong>Add custom integration</strong>.</p>
                </div>
              </div>
            </div>
            <div class="rounded-xl border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/40">
              <div class="flex items-start gap-2.5">
                <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[11px] font-bold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">2</span>
                <div class="min-w-0">
                  <p class="text-sm font-semibold text-slate-800 dark:text-slate-100">Copy the API keys</p>
                  <p class="mt-0.5 text-xs leading-relaxed text-slate-500 dark:text-slate-400">Copy the <strong>Content API Key</strong> and <strong>Admin API Key</strong> shown in the integration detail view.</p>
                </div>
              </div>
            </div>
            <div class="rounded-xl border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/40">
              <div class="flex items-start gap-2.5">
                <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[11px] font-bold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">3</span>
                <div class="min-w-0">
                  <p class="text-sm font-semibold text-slate-800 dark:text-slate-100">Save and test</p>
                  <p class="mt-0.5 text-xs leading-relaxed text-slate-500 dark:text-slate-400">Paste both keys above, add your Ghost URL, click <strong>Save credentials</strong>, then run a health check to verify.</p>
                </div>
              </div>
            </div>
            <a :href="DOCS_URL" target="_blank" rel="noopener" class="inline-block pt-1 text-xs font-semibold text-indigo-600 hover:underline dark:text-indigo-400">Full setup guide →</a>
          </div>
        </UiCard>
      </div>

      <!-- Stripe status section: shown once Ghost is connected -->
      <UiCard v-if="!loading && config.enabled">
        <template #header>
          <div class="min-w-0">
            <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">Stripe in Ghost</h2>
            <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">PayGlue checks your Ghost blog for a Stripe connection. This determines how members are created after a purchase.</p>
          </div>
        </template>
        <template #actions>
          <span v-if="stripeStatusLoading" class="whitespace-nowrap text-xs text-slate-400 dark:text-slate-500">Checking...</span>
        </template>

        <div v-if="!stripeStatusLoading && stripeStatus" class="space-y-3">
          <!-- Connected -->
          <div v-if="stripeStatus.connected" class="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 dark:border-emerald-500/30 dark:bg-emerald-500/10">
            <span class="h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-500"></span>
            <div>
              <p class="text-sm font-medium text-emerald-800 dark:text-emerald-300">Stripe connected in Ghost</p>
              <p v-if="stripeStatus.display_name" class="mt-0.5 text-xs text-emerald-700 dark:text-emerald-400">Account: {{ stripeStatus.display_name }}</p>
              <p class="mt-0.5 text-xs text-emerald-700 dark:text-emerald-400">Members who purchase will receive full access via a complimentary subscription.</p>
            </div>
          </div>

          <!-- Not connected -->
          <div v-else class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10">
            <div class="flex items-start gap-2">
              <span class="mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full bg-amber-400"></span>
              <div>
                <p class="text-sm font-medium text-amber-800 dark:text-amber-300">No Stripe connection found in Ghost</p>
                <p class="mt-0.5 text-xs text-amber-700 dark:text-amber-400">Members who purchase will be added as free members with a label. Native Ghost content gating will not apply. A PayGlue JS snippet can handle access control instead.</p>
              </div>
            </div>
            <div class="mt-3 space-y-2 rounded-xl border border-amber-200 bg-white p-3 dark:border-amber-500/30 dark:bg-slate-900">
              <p class="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">How to connect Stripe in Ghost</p>
              <div class="flex gap-2 text-xs text-slate-600 dark:text-slate-300">
                <span class="shrink-0 font-semibold text-slate-400 dark:text-slate-500">1.</span>
                <span>In your Ghost Admin, go to <strong>Settings</strong> and open <strong>Membership</strong>.</span>
              </div>
              <div class="flex gap-2 text-xs text-slate-600 dark:text-slate-300">
                <span class="shrink-0 font-semibold text-slate-400 dark:text-slate-500">2.</span>
                <span>Click <strong>Connect with Stripe</strong> and follow the OAuth flow. No API keys needed.</span>
              </div>
              <div class="flex gap-2 text-xs text-slate-600 dark:text-slate-300">
                <span class="shrink-0 font-semibold text-slate-400 dark:text-slate-500">3.</span>
                <span>Once connected, come back here and refresh. PayGlue will automatically detect the connection.</span>
              </div>
            </div>
          </div>
        </div>
      </UiCard>
    </div>
  </AppShell>
</template>

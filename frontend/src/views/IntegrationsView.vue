// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import {
  ApiHttpError,
  getIntegrationConfig,
  runIntegrationHealthCheck,
  setIntegrationCredentials,
  updateIntegrationConfig,
} from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { IntegrationConfig, IntegrationHealthStatus } from '../types/api'

type ProviderKey = 'payment' | 'cms'

const GHOST_DOCS_URL = 'https://docs.payglue.io/setup/ghost'
const POLAR_DOCS_URL = 'https://docs.payglue.io/setup/polar'

const session = useSessionStore()
const loading = ref(false)
const errorMessage = ref<string | null>(null)

const credentialSavingState = ref<Record<ProviderKey, boolean>>({ payment: false, cms: false })
const credentialSavedState = ref<Record<ProviderKey, boolean>>({ payment: false, cms: false })
const healthCheckingState = ref<Record<ProviderKey, boolean>>({ payment: false, cms: false })

const configs = reactive<Record<ProviderKey, IntegrationConfig>>({
  payment: {
    provider_key: 'payment',
    enabled: false,
    provider_type: 'polar',
    metadata: {},
  },
  cms: {
    provider_key: 'cms',
    enabled: false,
    provider_type: 'ghost',
    metadata: {},
  },
})

const polarCredentialForm = reactive({
  webhookSecret: '',
})
const editingSecret = ref(false)
const editingCmsCredentials = ref(false)
const cmsCredentialForm = reactive({
  apiBaseUrl: '',
  contentApiKey: '',
  adminApiKey: '',
})

const webhookUrl = computed(() =>
  `https://api.payglue.io/webhooks/polar?tenant=${session.activeTenantSlug}`
)

const copyWebhookUrl = async () => {
  await navigator.clipboard.writeText(webhookUrl.value)
}
const latestHealth = ref<Partial<Record<ProviderKey, IntegrationHealthStatus>>>({})

const canWrite = computed(() => {
  const role = session.activeMembership?.role
  return role === 'owner' || role === 'admin'
})

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) {
    throw new ApiHttpError('Tenant context is missing.', 400)
  }
  return { tenantSlug: session.activeTenantSlug, idToken: session.idToken }
}

const validateAbsoluteHttpUrl = (value: string, fieldLabel: string) => {
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    throw new Error(`${fieldLabel} must be a valid URL.`)
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error(`${fieldLabel} must start with http:// or https://.`)
  }
}


const buildCmsCredentials = () => {
  const apiBaseUrl = cmsCredentialForm.apiBaseUrl.trim()
  const contentApiKey = cmsCredentialForm.contentApiKey.trim()
  const adminApiKey = cmsCredentialForm.adminApiKey.trim()

  if (!apiBaseUrl) throw new Error('API URL is required.')
  validateAbsoluteHttpUrl(apiBaseUrl, 'API URL')
  if (!adminApiKey) throw new Error('Admin API key is required.')
  if (!adminApiKey.includes(':')) throw new Error('Admin API key must use the format <id>:<secret>.')

  const credentials: Record<string, string> = { api_base_url: apiBaseUrl, admin_api_key: adminApiKey }
  if (contentApiKey) credentials.content_api_key = contentApiKey
  return credentials
}

const buildPolarCredentials = () => {
  const webhookSecret = polarCredentialForm.webhookSecret.trim()
  if (!webhookSecret) throw new Error('Webhook secret is required.')
  return { webhook_secret: webhookSecret }
}

const loadOnboardingGhostData = () => {
  const slug = session.activeTenantSlug
  if (!slug) return
  try {
    const raw = localStorage.getItem(`payglue:ghost:${slug}`)
    if (!raw) return
    const data = JSON.parse(raw) as { url?: string; contentKey?: string; adminKey?: string }
    if (data.url) cmsCredentialForm.apiBaseUrl = data.url
    if (data.contentKey) cmsCredentialForm.contentApiKey = data.contentKey
    if (data.adminKey) cmsCredentialForm.adminApiKey = data.adminKey
  } catch {}
}

const loadProviderConfig = async (providerKey: ProviderKey) => {
  try {
    const { tenantSlug, idToken } = context()
    const config = await getIntegrationConfig(tenantSlug, idToken, providerKey)
    configs[providerKey] = config
    const health = config.metadata.health
    if (health && typeof health === 'object') {
      const candidate = health as Partial<IntegrationHealthStatus>
      if (
        typeof candidate.ok === 'boolean' &&
        typeof candidate.code === 'string' &&
        typeof candidate.message === 'string' &&
        typeof candidate.checked_at === 'string'
      ) {
        latestHealth.value[providerKey] = candidate as IntegrationHealthStatus
      }
    }
  } catch (error) {
    if (error instanceof ApiHttpError && error.status === 404) {
      return
    }
    throw error
  }
}

const load = async () => {
  loading.value = true
  errorMessage.value = null
  try {
    await Promise.all([loadProviderConfig('payment'), loadProviderConfig('cms')])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to load integrations.'
  } finally {
    loading.value = false
  }
}


const saveCredentials = async (providerKey: ProviderKey) => {
  if (!canWrite.value) return
  credentialSavingState.value[providerKey] = true
  errorMessage.value = null
  try {
    const credentials = providerKey === 'cms' ? buildCmsCredentials() : buildPolarCredentials()
    const { tenantSlug, idToken } = context()
    await updateIntegrationConfig(tenantSlug, idToken, providerKey, {
      enabled: true,
      provider_type: providerKey === 'cms' ? 'ghost' : 'polar',
      metadata: configs[providerKey].metadata ?? {},
    })
    await setIntegrationCredentials(tenantSlug, idToken, providerKey, credentials)
    if (providerKey === 'payment') {
      polarCredentialForm.webhookSecret = ''
      editingSecret.value = false
    } else {
      cmsCredentialForm.contentApiKey = ''
      cmsCredentialForm.adminApiKey = ''
      editingCmsCredentials.value = false
    }
    configs[providerKey].enabled = true
    credentialSavedState.value[providerKey] = true
    setTimeout(() => { credentialSavedState.value[providerKey] = false }, 3000)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to save credentials.'
  } finally {
    credentialSavingState.value[providerKey] = false
  }
}

const checkHealth = async (providerKey: ProviderKey) => {
  if (!canWrite.value) return
  healthCheckingState.value[providerKey] = true
  errorMessage.value = null
  try {
    const { tenantSlug, idToken } = context()
    if (!configs[providerKey].provider_key) {
      await updateIntegrationConfig(tenantSlug, idToken, providerKey, {
        enabled: true,
        provider_type: providerKey === 'cms' ? 'ghost' : 'polar',
        metadata: {},
      })
    }
    latestHealth.value[providerKey] = await runIntegrationHealthCheck(tenantSlug, idToken, providerKey)
    setTimeout(() => { latestHealth.value[providerKey] = undefined }, 5000)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to run health check.'
  } finally {
    healthCheckingState.value[providerKey] = false
  }
}

onMounted(() => {
  load()
  loadOnboardingGhostData()
})
</script>

<template>
  <AppShell>
    <div class="space-y-6">
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h1 class="text-xl font-semibold text-slate-900">Integrations</h1>
        <p class="mt-1 text-sm text-slate-600">
          Configure payment and CMS providers, securely write credentials, and validate provider health.
        </p>
        <p v-if="!canWrite" class="mt-3 text-xs text-amber-700">
          Your role can view integration settings but cannot modify provider configuration.
        </p>
        <p v-if="errorMessage" class="mt-3 text-sm text-rose-700">{{ errorMessage }}</p>
      </section>

      <p v-if="loading" class="text-sm text-slate-500">Loading integrations...</p>

      <section
        v-for="providerKey in ['payment', 'cms']"
        :key="providerKey"
        class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <h2 class="text-base font-semibold text-slate-900">
          {{ providerKey === 'payment' ? 'Payment integration' : 'Ghost CMS Integration' }}
        </h2>

        <div class="mt-6">
          <template v-if="providerKey === 'payment'">
            <div class="grid gap-6 lg:grid-cols-2">
              <!-- Left: fields -->
              <div class="space-y-3">
                <div>
                  <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Webhook URL</span>
                  <div class="flex gap-2">
                    <input
                      :value="webhookUrl"
                      readonly
                      class="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-xs text-slate-700"
                    />
                    <button
                      type="button"
                      class="flex-shrink-0 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                      @click="copyWebhookUrl"
                    >Copy</button>
                  </div>
                </div>
                <label class="block">
                  <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Webhook secret</span>
                  <div v-if="configs.payment.enabled && !editingSecret" class="flex items-center gap-2">
                    <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-sm tracking-widest text-slate-400">••••••••••••</div>
                    <button
                      v-if="canWrite"
                      type="button"
                      class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                      @click="editingSecret = true; polarCredentialForm.webhookSecret = ''"
                    >Update</button>
                  </div>
                  <input
                    v-else
                    v-model="polarCredentialForm.webhookSecret"
                    type="password"
                    placeholder="whsec_..."
                    autocomplete="off"
                    class="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-sm"
                    :disabled="!canWrite"
                  />
                </label>
                <div class="flex items-center gap-1.5 text-xs">
                  <template v-if="configs.payment.enabled">
                    <span class="inline-block h-2 w-2 rounded-full bg-emerald-500"></span>
                    <span class="font-medium text-emerald-700">Connected</span>
                  </template>
                  <template v-else>
                    <span class="inline-block h-2 w-2 rounded-full bg-rose-500"></span>
                    <span class="font-medium text-rose-600">Not Connected</span>
                    <span class="text-slate-400">— a webhook secret is required</span>
                  </template>
                </div>
              </div>

              <!-- Right: step-by-step guide -->
              <div class="space-y-2">
                <p class="text-xs font-semibold uppercase tracking-widest text-indigo-600">How to set up</p>
                <div class="space-y-2">
                  <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
                    <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 1</p>
                    <p class="mt-0.5 text-sm font-medium text-slate-800">Open Polar Settings</p>
                    <p class="mt-0.5 text-xs text-slate-500">In your Polar dashboard, go to <strong>Settings</strong> and click <strong>Webhooks</strong> in the sidebar.</p>
                  </div>
                  <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
                    <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 2</p>
                    <p class="mt-0.5 text-sm font-medium text-slate-800">Add endpoint</p>
                    <p class="mt-0.5 text-xs text-slate-500">Click <strong>+ Add endpoint</strong>. Set format to <strong>Raw</strong>, paste the Webhook URL from the left, then select <strong>All events</strong>. Click <strong>Save</strong>.</p>
                  </div>
                  <div class="rounded-lg border border-slate-100 bg-slate-50 p-3">
                    <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Step 3</p>
                    <p class="mt-0.5 text-sm font-medium text-slate-800">Copy the secret</p>
                    <p class="mt-0.5 text-xs text-slate-500">After saving, Polar shows a <strong>Webhook secret</strong>. Copy it and paste it into the field on the left, then click <strong>Save Polar credentials</strong>.</p>
                  </div>
                </div>
                <a :href="POLAR_DOCS_URL" target="_blank" rel="noopener" class="inline-block pt-1 text-xs text-blue-700 hover:underline">Full setup guide</a>
              </div>
            </div>
          </template>
          <template v-else>
            <div class="space-y-3">
              <div v-if="configs.cms.enabled && !editingCmsCredentials" class="space-y-3">
                <div>
                  <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Content API key</span>
                  <div class="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-sm tracking-widest text-slate-400">••••••••••••</div>
                </div>
                <div>
                  <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Admin API key</span>
                  <div class="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-sm tracking-widest text-slate-400">••••••••••••</div>
                </div>
                <div>
                  <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Ghost URL</span>
                  <div class="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-slate-600">{{ cmsCredentialForm.apiBaseUrl || '—' }}</div>
                </div>
                <button
                  v-if="canWrite"
                  type="button"
                  class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  @click="editingCmsCredentials = true"
                >Update credentials</button>
              </div>
              <template v-else>
                <label class="block text-sm text-slate-700">
                  <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Content API key</span>
                  <input
                    v-model="cmsCredentialForm.contentApiKey"
                    aria-label="Content API key"
                    class="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-sm"
                    placeholder="acac4d839f6cfa04b907a04cf4..."
                    :disabled="!canWrite"
                  />
                </label>
                <label class="block text-sm text-slate-700">
                  <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Admin API key</span>
                  <input
                    v-model="cmsCredentialForm.adminApiKey"
                    aria-label="Admin API key"
                    class="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-sm"
                    placeholder="6a3145b0e72c430001fdcd39:f0533b2b..."
                    :disabled="!canWrite"
                  />
                </label>
                <label class="block text-sm text-slate-700">
                  <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Ghost URL</span>
                  <input
                    v-model="cmsCredentialForm.apiBaseUrl"
                    aria-label="Ghost URL"
                    class="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
                    placeholder="https://www.yourblog.com"
                    :disabled="!canWrite"
                  />
                </label>
              </template>
              <p class="text-xs text-slate-400">
                Need help?
                <a :href="GHOST_DOCS_URL" target="_blank" rel="noopener" class="text-blue-700 hover:underline">View setup guide</a>
              </p>
            </div>
          </template>
          <div class="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="!canWrite || credentialSavingState[providerKey as ProviderKey]"
              @click="saveCredentials(providerKey as ProviderKey)"
            >
              {{ credentialSavingState[providerKey as ProviderKey] ? 'Saving...' : credentialSavedState[providerKey as ProviderKey] ? 'Saved!' : `Save ${providerKey === 'cms' ? 'Ghost' : 'Polar'} credentials` }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!canWrite || healthCheckingState[providerKey as ProviderKey]"
              @click="checkHealth(providerKey as ProviderKey)"
            >
              {{ healthCheckingState[providerKey as ProviderKey] ? 'Checking...' : 'Run health check' }}
            </button>
          </div>
        </div>

        <div v-if="latestHealth[providerKey as ProviderKey]" class="mt-4 rounded-lg border p-3 text-sm"
          :class="latestHealth[providerKey as ProviderKey]?.ok ? 'border-emerald-200 bg-emerald-50' : 'border-rose-200 bg-rose-50'">
          <p class="font-semibold" :class="latestHealth[providerKey as ProviderKey]?.ok ? 'text-emerald-800' : 'text-rose-800'">
            {{ latestHealth[providerKey as ProviderKey]?.ok ? 'Connection established' : 'Connection failed' }}
          </p>
          <p class="mt-0.5 text-xs" :class="latestHealth[providerKey as ProviderKey]?.ok ? 'text-emerald-700' : 'text-rose-700'">
            {{ latestHealth[providerKey as ProviderKey]?.message }}
          </p>
        </div>
      </section>
    </div>
  </AppShell>
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import CopyButton from '../components/CopyButton.vue'
import UpgradeBanner from '../components/UpgradeBanner.vue'
import { PageHeader, UiCard, UiButton, FormField, ProviderLogo } from '../components/ui'
import {
  ApiHttpError,
  getIntegrationConfig,
  getLemonSqueezyStores,
  getPolarProducts,
  runIntegrationHealthCheck,
  setIntegrationCredentials,
  updateIntegrationConfig,
} from '../lib/api'
import { CONNECTION_PROVIDERS, WEBHOOK_URL_HINT, type ProviderKey } from '../lib/connectionProviders'
import { isPlanLimitError, planKeyFromError } from '../lib/planUpgrade'
import { useSessionStore } from '../stores/session'
import type { IntegrationConfig, IntegrationCredentialWriteResult, IntegrationHealthStatus } from '../types/api'

// The provider this detail view renders. Supplied via the route's `props`.
const props = defineProps<{ provider: ProviderKey }>()

const session = useSessionStore()

const meta = computed(() => CONNECTION_PROVIDERS[props.provider])

const loading = ref(false)
const errorMessage = ref<string | null>(null)
const errorMessagePlan = ref<string | null>(null)
const saving = ref(false)
const saved = ref(false)
const healthChecking = ref(false)
const latestHealth = ref<IntegrationHealthStatus | undefined>()
const webhookRegistrationMessage = ref<string | null>(null)
const webhookRegistrationOk = ref(true)

const config = reactive<IntegrationConfig>({
  provider_key: props.provider,
  enabled: false,
  provider_type: props.provider,
  metadata: {},
})

// Per-field state keyed by the credential key. `form` holds the newly-typed
// value, `stored` whether a saved secret exists (→ show dots), `editing`
// whether the user chose to overwrite a stored value.
const form = reactive<Record<string, string>>({})
const stored = reactive<Record<string, boolean>>({})
const editing = reactive<Record<string, boolean>>({})

// Lemon Squeezy store selector.
interface LsStore { id: string; name: string; slug: string }
const stores = ref<LsStore[]>([])
const storesLoading = ref(false)
const storesError = ref<string | null>(null)
const selectedStoreId = ref('')

// Polar rename banner.
const hasPendingRename = ref(false)
const renameConfirmed = ref(false)

const canWrite = computed(() => {
  const r = session.activeMembership?.role
  return r === 'owner' || r === 'admin'
})

const webhookUrl = computed(
  () => `https://api.payglue.io/webhooks/${props.provider}?tenant=${session.activeTenantSlug}&key=${session.webhookSecret ?? ''}`,
)

const pendingRenameKey = computed(() =>
  session.activeTenantSlug ? `payglue:pending-rename:${session.activeTenantSlug}` : null,
)

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) throw new ApiHttpError('Missing context.', 400)
  return { tenantSlug: session.activeTenantSlug, idToken: session.idToken }
}

const resetFieldState = () => {
  for (const field of meta.value.fields) {
    form[field.key] = ''
    stored[field.key] = false
    editing[field.key] = false
  }
}

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
  resetFieldState()
  try {
    const { tenantSlug, idToken } = context()
    const c = await getIntegrationConfig(tenantSlug, idToken, meta.value.key)
    Object.assign(config, c)
    const h = c.metadata.health
    if (h && typeof (h as { ok?: unknown }).ok === 'boolean') latestHealth.value = h as IntegrationHealthStatus
    const maskedKeys: string[] = (c.metadata as { credential_ref?: { masked_keys?: string[] } })?.credential_ref?.masked_keys ?? []
    for (const field of meta.value.fields) {
      if (field.detect === 'credential_ref') stored[field.key] = maskedKeys.includes(field.key)
      else if (field.detect === 'polar_token') stored[field.key] = false // resolved below
      else stored[field.key] = config.enabled // 'enabled' (webhook/signing secret)
    }
    // Polar's API token is detected via the products endpoint, not masked_keys.
    if (meta.value.fields.some((f) => f.detect === 'polar_token')) {
      try {
        const products = await getPolarProducts(tenantSlug, idToken)
        for (const field of meta.value.fields) {
          if (field.detect === 'polar_token') stored[field.key] = products.has_token
        }
      } catch { /* token check is non-critical */ }
    }
    // Lemon Squeezy: load the store list once we know the API key is stored.
    if (meta.value.hasStore && stored['api_key']) loadStores()
    if (meta.value.renameBanner && pendingRenameKey.value) {
      hasPendingRename.value = localStorage.getItem(pendingRenameKey.value) === '1'
    }
    await session.getWebhookSecret()
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

const showSaveButton = computed(() => {
  if (!config.enabled) return true
  if (meta.value.fields.some((f) => editing[f.key] || (form[f.key] ?? '').trim())) return true
  if (meta.value.hasStore && selectedStoreId.value) return true
  return false
})

const save = async () => {
  if (!canWrite.value) return
  saving.value = true
  errorMessage.value = null
  errorMessagePlan.value = null
  webhookRegistrationMessage.value = null
  try {
    const required = meta.value.requireOnFirstSave
    if (required && !config.enabled && !(form[required] ?? '').trim()) {
      const label = meta.value.fields.find((f) => f.key === required)?.label ?? 'This field'
      throw new Error(`${label} is required.`)
    }
    const { tenantSlug, idToken } = context()
    await updateIntegrationConfig(tenantSlug, idToken, meta.value.key, {
      enabled: true,
      provider_type: meta.value.key,
      metadata: config.metadata ?? {},
    })

    const creds: Record<string, string> = {}
    for (const field of meta.value.fields) {
      const v = (form[field.key] ?? '').trim()
      if (v) creds[field.key] = v
    }
    if (meta.value.hasStore && selectedStoreId.value) creds.store_id = selectedStoreId.value

    if (Object.keys(creds).length > 0) {
      // Merge always-on / derived credentials (PayPal sandbox flag, Paddle
      // sandbox-from-prefix) exactly as the old per-provider views did.
      Object.assign(creds, meta.value.staticCreds ?? {})
      if (meta.value.computeCreds) Object.assign(creds, meta.value.computeCreds(form))
      const result: IntegrationCredentialWriteResult = await setIntegrationCredentials(
        tenantSlug,
        idToken,
        meta.value.key,
        creds,
      )
      const maskedKeys: string[] = result.credential_ref?.masked_keys ?? []
      for (const field of meta.value.fields) {
        if (field.detect === 'credential_ref') stored[field.key] = maskedKeys.includes(field.key)
        else if (field.detect === 'polar_token' && (form[field.key] ?? '').trim()) stored[field.key] = true
      }
      // Gumroad (and any provider that registers webhooks server-side) reports
      // the registration outcome -- surface it.
      const reg = result.webhook_registration
      if (reg && (reg.registered?.length || reg.failed?.length)) {
        if (reg.failed?.length) {
          webhookRegistrationOk.value = false
          webhookRegistrationMessage.value = `Some webhook events could not be registered: ${reg.failed.join(', ')}.`
        } else {
          webhookRegistrationOk.value = true
          webhookRegistrationMessage.value = 'Webhook events registered automatically.'
        }
      }
      if (meta.value.hasStore && ((form['api_key'] ?? '').trim() || (stored['api_key'] && !stores.value.length))) {
        await loadStores()
      }
    }

    config.enabled = true
    for (const field of meta.value.fields) {
      form[field.key] = ''
      editing[field.key] = false
      if (field.detect === 'enabled') stored[field.key] = true
    }
    saved.value = true
    setTimeout(() => { saved.value = false }, 3000)
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Unable to save.'
    errorMessagePlan.value = isPlanLimitError(e) ? planKeyFromError(e) : null
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
      await updateIntegrationConfig(tenantSlug, idToken, meta.value.key, { enabled: true, provider_type: meta.value.key, metadata: {} })
    }
    latestHealth.value = await runIntegrationHealthCheck(tenantSlug, idToken, meta.value.key)
    setTimeout(() => { latestHealth.value = undefined }, 5000)
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Health check failed.'
  } finally {
    healthChecking.value = false
  }
}

const startEditing = (key: string) => {
  editing[key] = true
  form[key] = ''
}

const showStore = computed(() => meta.value.hasStore && (stored['api_key'] || (form['api_key'] ?? '').trim()))

onMounted(load)
// Re-load when navigating between providers without unmounting the view.
watch(() => props.provider, () => {
  Object.assign(config, { provider_key: props.provider, enabled: false, provider_type: props.provider, metadata: {} })
  latestHealth.value = undefined
  errorMessage.value = null
  webhookRegistrationMessage.value = null
  stores.value = []
  selectedStoreId.value = ''
  hasPendingRename.value = false
  load()
})
</script>

<template>
  <AppShell>
    <div class="space-y-5">
      <!-- Publication-rename webhook warning (Polar) -->
      <div v-if="hasPendingRename" class="rounded-2xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-500/40 dark:bg-amber-500/10">
        <div class="flex items-start gap-3">
          <svg class="mt-0.5 h-5 w-5 shrink-0 text-amber-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          <div class="flex-1">
            <p class="font-semibold text-amber-900 dark:text-amber-200">Publication renamed, update your webhook URL</p>
            <p class="mt-1 text-sm text-amber-800 dark:text-amber-300/90">Your publication slug changed. Please update the endpoint URL in your {{ meta.name }} dashboard to:</p>
            <code class="mt-2 block rounded-lg bg-amber-100 px-3 py-1.5 font-mono text-xs text-amber-900 dark:bg-amber-500/20 dark:text-amber-200">{{ webhookUrl }}</code>
            <label class="mt-3 flex cursor-pointer items-center gap-2">
              <input v-model="renameConfirmed" type="checkbox" class="h-4 w-4 accent-amber-600" @change="renameConfirmed && dismissRenameWarning()" />
              <span class="text-sm text-amber-900 dark:text-amber-200">I have updated the webhook URL in {{ meta.name }}. Dismiss this warning.</span>
            </label>
          </div>
        </div>
      </div>

      <PageHeader :title="meta.name" :description="meta.blurb">
        <template #actions>
          <ProviderLogo :provider="meta.key" size="md" />
        </template>
      </PageHeader>

      <p v-if="!canWrite" class="text-xs text-amber-600 dark:text-amber-400">Your role can view but cannot modify this configuration.</p>
      <UpgradeBanner v-if="errorMessage && errorMessagePlan" :message="errorMessage" :plan-key="errorMessagePlan" />
      <p v-else-if="errorMessage" class="text-sm text-rose-600 dark:text-rose-400">{{ errorMessage }}</p>

      <p v-if="loading" class="px-1 text-sm text-slate-500 dark:text-slate-400">Loading...</p>

      <div v-if="!loading" class="grid gap-5 lg:grid-cols-3">
        <!-- Left: credential form -->
        <UiCard class="lg:col-span-2">
          <div class="space-y-4">
            <!-- Webhook URL -->
            <FormField label="Webhook URL" :hint="WEBHOOK_URL_HINT">
              <div class="flex gap-2">
                <input :value="webhookUrl" readonly class="pg-input pg-mono" />
                <CopyButton :text="webhookUrl" />
              </div>
            </FormField>

            <!-- Credential fields -->
            <FormField
              v-for="field in meta.fields"
              :key="field.key"
              :label="field.label"
              :optional="field.optional"
              :hint="field.hint"
            >
              <div v-if="stored[field.key] && !editing[field.key]" class="flex items-center gap-2">
                <div class="pg-input pg-dots flex-1">••••••••••••</div>
                <UiButton v-if="canWrite" size="sm" variant="default" @click="startEditing(field.key)">Update</UiButton>
              </div>
              <input
                v-else
                v-model="form[field.key]"
                :type="field.inputType ?? 'password'"
                :placeholder="field.placeholder"
                autocomplete="off"
                :disabled="!canWrite"
                class="pg-input pg-mono"
              />
            </FormField>

            <!-- Lemon Squeezy store selector -->
            <FormField
              v-if="showStore"
              label="Store"
              hint="Limits product fetching to this store. Required if your API key has access to multiple stores."
            >
              <p v-if="storesLoading" class="text-xs text-slate-400 dark:text-slate-500">Loading stores...</p>
              <template v-else>
                <p v-if="storesError" class="mb-1 text-xs text-amber-600 dark:text-amber-400">{{ storesError }}</p>
                <select v-model="selectedStoreId" :disabled="!canWrite" class="pg-input">
                  <option value="">Select your store</option>
                  <option v-for="s in stores" :key="s.id" :value="s.id">{{ s.name }} ({{ s.slug }})</option>
                </select>
              </template>
            </FormField>

            <!-- Status -->
            <div class="flex items-center gap-1.5 text-xs">
              <span class="inline-block h-2 w-2 rounded-full" :class="config.enabled ? 'bg-emerald-500' : 'bg-rose-500'"></span>
              <span v-if="config.enabled" class="font-medium text-emerald-600 dark:text-emerald-400">Connected</span>
              <span v-else class="font-medium text-rose-600 dark:text-rose-400">{{ meta.notConnectedMsg }}</span>
            </div>

            <p v-if="webhookRegistrationMessage" class="text-xs" :class="webhookRegistrationOk ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'">{{ webhookRegistrationMessage }}</p>

            <!-- Actions -->
            <div class="flex flex-wrap gap-2 pt-1">
              <UiButton v-if="showSaveButton" variant="primary" :disabled="!canWrite || saving" @click="save">
                {{ saving ? 'Saving...' : saved ? 'Saved!' : 'Save credentials' }}
              </UiButton>
              <UiButton variant="default" :disabled="!canWrite || healthChecking" @click="runHealthCheck">
                {{ healthChecking ? 'Checking...' : 'Run health check' }}
              </UiButton>
              <UiButton v-if="config.enabled" variant="accent" :to="`/t/${session.activeTenantSlug}/mappings`">
                Test this connection →
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
        <UiCard title="How to set up" :description="`Provider-specific, ${meta.steps.length} steps.`">
          <div class="space-y-2.5">
            <div
              v-for="(step, i) in meta.steps"
              :key="i"
              class="rounded-xl border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/40"
            >
              <div class="flex items-start gap-2.5">
                <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[11px] font-bold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">{{ i + 1 }}</span>
                <div class="min-w-0">
                  <p class="text-sm font-semibold text-slate-800 dark:text-slate-100">{{ step.title }}</p>
                  <!-- eslint-disable-next-line vue/no-v-html -->
                  <p class="mt-0.5 text-xs leading-relaxed text-slate-500 dark:text-slate-400" v-html="step.bodyHtml"></p>
                  <ul v-if="step.events" class="mt-1.5 space-y-0.5 font-mono text-[11px] text-slate-600 dark:text-slate-400">
                    <li v-for="ev in step.events" :key="ev">{{ ev }}</li>
                  </ul>
                </div>
              </div>
            </div>
            <a :href="meta.docsUrl" target="_blank" rel="noopener" class="inline-block pt-1 text-xs font-semibold text-indigo-600 hover:underline dark:text-indigo-400">Full setup guide →</a>
          </div>
        </UiCard>
      </div>
    </div>
  </AppShell>
</template>

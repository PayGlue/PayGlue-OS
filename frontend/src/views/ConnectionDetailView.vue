// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import CopyButton from '../components/CopyButton.vue'
import UpgradeBanner from '../components/UpgradeBanner.vue'
import { PageHeader, UiCard, UiButton, FormField, ProviderLogo, StatusPill } from '../components/ui'
import { webhookUrl as buildWebhookUrl } from '../lib/publicUrls'
import {
  ApiHttpError,
  disconnectIntegration,
  getIntegrationConfig,
  getPolarProducts,
  listMappings,
  registerIntegrationWebhooks,
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
// A fresh form starts neutral. Rose only once a save has actually failed,
// not before anybody has typed anything (PG-402).
const saveFailed = ref(false)
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

// Polar rename banner.
const hasPendingRename = ref(false)
const renameConfirmed = ref(false)

const canWrite = computed(() => {
  const r = session.activeMembership?.role
  return r === 'owner' || r === 'admin'
})

// Empty string until the tenant's key is actually known. The URL is worthless
// without it, and the previous `?? ''` fallback rendered a copyable URL ending
// in a bare "&key=" that the provider then rejected (PG-219). The template
// shows a retry in place of the field rather than a URL that cannot work.
const webhookUrl = computed(() =>
  session.webhookSecret
    ? buildWebhookUrl(props.provider, session.activeTenantSlug ?? '', session.webhookSecret)
    : '',
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
    if (meta.value.renameBanner && pendingRenameKey.value) {
      hasPendingRename.value = localStorage.getItem(pendingRenameKey.value) === '1'
    }
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
  // Saving again registers the webhooks again, so it stays useful when
  // every field is already stored.
  if (meta.value.registersWebhooks) return true
  if (meta.value.fields.some((f) => editing[f.key] || (form[f.key] ?? '').trim())) return true
  return false
})

// Gumroad (and any provider that registers webhooks server-side) reports
// the registration outcome -- surface it.
const showWebhookRegistration = (reg: IntegrationCredentialWriteResult['webhook_registration']) => {
  if (!reg || !(reg.registered?.length || reg.failed?.length)) return
  if (reg.failed?.length) {
    webhookRegistrationOk.value = false
    webhookRegistrationMessage.value = reg.detail
      ? `The webhook could not be set up: ${reg.detail}`
      : `Some webhook events could not be registered: ${reg.failed.join(', ')}.`
  } else {
    webhookRegistrationOk.value = true
    webhookRegistrationMessage.value = 'Webhook events registered automatically.'
  }
}

const save = async () => {
  if (!canWrite.value) return
  saving.value = true
  errorMessage.value = null
  errorMessagePlan.value = null
  disconnectedMessage.value = null
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
      // Keep the page's copy current, so a second Save without a reload does
      // not send metadata from before this one.
      if (result.credential_ref) config.metadata = { ...(config.metadata ?? {}), credential_ref: result.credential_ref }
      for (const field of meta.value.fields) {
        if (field.detect === 'credential_ref') stored[field.key] = maskedKeys.includes(field.key)
        else if (field.detect === 'polar_token' && (form[field.key] ?? '').trim()) stored[field.key] = true
      }
      showWebhookRegistration(result.webhook_registration)
    } else if (meta.value.registersWebhooks && config.enabled) {
      const result = await registerIntegrationWebhooks(tenantSlug, idToken, meta.value.key as 'gumroad' | 'digistore24')
      showWebhookRegistration(result.webhook_registration)
    }

    config.enabled = true
    for (const field of meta.value.fields) {
      form[field.key] = ''
      editing[field.key] = false
      if (field.detect === 'enabled') stored[field.key] = true
    }
    saved.value = true
    saveFailed.value = false
    setTimeout(() => { saved.value = false }, 3000)
  } catch (e) {
    saveFailed.value = true
    errorMessage.value = e instanceof Error ? e.message : 'Unable to save.'
    errorMessagePlan.value = isPlanLimitError(e) ? planKeyFromError(e) : null
  } finally {
    saving.value = false
  }
}

const NUMBER_WORDS = ['', 'one', 'two', 'three', 'four', 'five']
const freshFormHint = computed(() => {
  const required = meta.value.fields.filter((field) => !field.optional).length
  if (required <= 1) return 'Not connected yet. Fill in the field and save.'
  return `Not connected yet. Fill in the ${NUMBER_WORDS[required] ?? required} fields and save.`
})

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

// Disconnect: deletes the stored credentials and the connection, so the page
// is empty again. Asks first and says what stays: mappings and embeds are kept
// for a later reconnect, members already in Ghost keep their access.
const confirmingDisconnect = ref(false)
const disconnecting = ref(false)
const disconnectedMessage = ref<string | null>(null)
const affectedMappings = ref<number | null>(null)

const hasConnection = computed(() => config.enabled || meta.value.fields.some((f) => stored[f.key]))

const askDisconnect = async () => {
  affectedMappings.value = null
  confirmingDisconnect.value = true
  try {
    const { tenantSlug, idToken } = context()
    const mappings = await listMappings(tenantSlug, idToken)
    affectedMappings.value = mappings.filter((m) => m.payment_provider === meta.value.key).length
  } catch { /* the count is informative only */ }
}

const disconnect = async () => {
  if (!canWrite.value) return
  disconnecting.value = true
  errorMessage.value = null
  try {
    const { tenantSlug, idToken } = context()
    await disconnectIntegration(tenantSlug, idToken, meta.value.key)
    Object.assign(config, { provider_key: props.provider, enabled: false, provider_type: props.provider, metadata: {} })
    resetFieldState()
    latestHealth.value = undefined
    webhookRegistrationMessage.value = null
    confirmingDisconnect.value = false
    disconnectedMessage.value = `${meta.value.name} is disconnected and the saved keys are deleted. Remove the webhook and the API key in your ${meta.value.name} dashboard as well.`
  } catch (e) {
    confirmingDisconnect.value = false
    errorMessage.value = e instanceof Error ? e.message : 'Unable to disconnect.'
  } finally {
    disconnecting.value = false
  }
}

const startEditing = (key: string) => {
  editing[key] = true
  form[key] = ''
}

// Deliberately not part of load(). The webhook secret is tenant-level and has
// nothing to do with this provider's config, but it used to be fetched as the
// last statement of load()'s try block -- so a provider that had never been
// configured 404'd on the config and returned early, skipping the fetch and
// leaving the webhook URL with an empty "&key=" (PG-219). That hit every
// first-time setup, on all eight providers, and looked fine until the provider
// rejected the webhook.
const loadWebhookSecret = () => {
  void session.getWebhookSecret()
}

onMounted(() => {
  load()
  loadWebhookSecret()
})
// Re-load when navigating between providers without unmounting the view.
watch(() => props.provider, () => {
  Object.assign(config, { provider_key: props.provider, enabled: false, provider_type: props.provider, metadata: {} })
  latestHealth.value = undefined
  errorMessage.value = null
  webhookRegistrationMessage.value = null
  disconnectedMessage.value = null
  confirmingDisconnect.value = false
  hasPendingRename.value = false
  load()
  // Cached per tenant in the store, so this is a no-op once loaded -- but it
  // gives a failed earlier fetch another chance instead of staying broken.
  loadWebhookSecret()
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
            <code v-if="webhookUrl" class="mt-2 block rounded-lg bg-amber-100 px-3 py-1.5 font-mono text-xs text-amber-900 dark:bg-amber-500/20 dark:text-amber-200">{{ webhookUrl }}</code>
            <p v-else class="mt-2 text-sm text-amber-800 dark:text-amber-300/90">Loading your webhook URL, it appears below in a moment.</p>
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
            <!-- Status in the card's head, where it is seen first, instead of
                 under the last field (PG-402). -->
            <div class="flex items-center justify-between gap-3 border-b border-slate-100 pb-3 dark:border-slate-800">
              <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ meta.name }}</h2>
              <StatusPill :tone="config.enabled ? 'good' : 'neutral'" dot>{{ config.enabled ? 'Connected' : 'Not connected yet' }}</StatusPill>
            </div>
            <!-- Webhook URL -->
            <FormField label="Webhook URL" :hint="meta.registersWebhooks ? undefined : (meta.webhookUrlHint ?? WEBHOOK_URL_HINT)">
              <div v-if="webhookUrl" class="flex gap-2">
                <input :value="webhookUrl" readonly class="pg-input pg-mono" />
                <!-- PayGlue registers the address itself, so there is nothing to copy. -->
                <CopyButton v-if="!meta.registersWebhooks" :text="webhookUrl" />
              </div>
              <!-- The hint has its own v-if. Chained to the states below, a loaded
                   URL on a provider without the hint fell through to the loading
                   line and showed it forever (PG-402). -->
              <p
                v-if="webhookUrl && meta.registersWebhooks"
                class="mt-2 rounded-lg border border-indigo-100 bg-indigo-50 px-3 py-2 text-sm text-indigo-800 dark:border-indigo-900/50 dark:bg-indigo-950/40 dark:text-indigo-200"
              >
                {{ meta.webhookUrlHint }}
              </p>
              <template v-if="!webhookUrl">
                <div v-if="session.webhookSecretError" class="flex items-center gap-3">
                  <p class="text-sm text-rose-600 dark:text-rose-400">Could not load your webhook key. The URL is incomplete without it, so please retry before copying.</p>
                  <UiButton size="sm" variant="default" class="shrink-0" @click="loadWebhookSecret">Retry</UiButton>
                </div>
                <p v-else class="text-sm text-slate-500 dark:text-slate-400">Loading your webhook URL...</p>
              </template>
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
            <!-- Not connected yet: neutral until a save has failed. -->
            <div v-if="!config.enabled" class="flex items-center gap-1.5 text-xs" role="status">
              <span class="inline-block h-2 w-2 rounded-full" :class="saveFailed ? 'bg-rose-500' : 'bg-slate-300 dark:bg-slate-600'"></span>
              <span v-if="saveFailed" class="font-medium text-rose-700 dark:text-rose-400">{{ meta.notConnectedMsg }}</span>
              <span v-else class="text-slate-600 dark:text-slate-300">{{ freshFormHint }}</span>
            </div>

            <p v-if="disconnectedMessage" class="text-xs text-slate-600 dark:text-slate-300">{{ disconnectedMessage }}</p>

            <p v-if="webhookRegistrationMessage" class="text-xs" :class="webhookRegistrationOk ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'">{{ webhookRegistrationMessage }}</p>

            <!-- Actions -->
            <div class="flex flex-wrap gap-2 pt-1">
              <!-- A health check on an empty form can only fail. -->
              <UiButton
                variant="default"
                :disabled="!canWrite || healthChecking || !config.enabled"
                :title="config.enabled ? undefined : 'Save credentials first'"
                @click="runHealthCheck"
              >
                {{ healthChecking ? 'Checking...' : 'Run health check' }}
              </UiButton>
              <UiButton v-if="config.enabled" variant="accent" :to="`/t/${session.activeTenantSlug}/mappings`">
                Test this connection →
              </UiButton>
              <!-- Save sits rightmost and Disconnect next to it, so a quick
                   click at the end of the row saves rather than disconnects. -->
              <div class="flex gap-2 sm:ml-auto">
                <UiButton v-if="canWrite && hasConnection" variant="danger" @click="askDisconnect">
                  Disconnect
                </UiButton>
                <UiButton v-if="showSaveButton" variant="primary" :disabled="!canWrite || saving" @click="save">
                  {{ saving ? 'Saving...' : saved ? 'Saved!' : 'Save credentials' }}
                </UiButton>
              </div>
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

    <!-- Disconnect confirmation. Deleting the keys cannot be undone, so it
         says what goes, what stays, and what is left to do at the provider. -->
    <div
      v-if="confirmingDisconnect"
      class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4"
      @click.self="confirmingDisconnect = false"
    >
      <div class="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <h2 class="text-base font-semibold text-slate-900 dark:text-slate-100">Disconnect {{ meta.name }}?</h2>

        <div class="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm dark:border-slate-700 dark:bg-slate-800/50">
          <p class="font-medium text-slate-800 dark:text-slate-100">What happens</p>
          <ul class="mt-2 list-inside list-disc space-y-1 text-slate-600 dark:text-slate-300">
            <li>The saved keys for {{ meta.name }} are deleted from PayGlue. This cannot be undone.</li>
            <li>Webhooks from {{ meta.name }} are rejected until you connect again.</li>
            <li>Members already in Ghost keep their access.</li>
            <li v-if="affectedMappings">
              {{ affectedMappings }} product {{ affectedMappings === 1 ? 'mapping stays' : 'mappings stay' }}, together with your buy buttons and pricing tables. They work again once you reconnect.
            </li>
          </ul>
        </div>

        <p class="mt-4 text-sm text-slate-600 dark:text-slate-300">
          Afterwards, remove the webhook and the API key in your {{ meta.name }} dashboard as well.
        </p>

        <div class="mt-6 flex justify-end gap-3">
          <UiButton variant="ghost" size="sm" @click="confirmingDisconnect = false">Cancel</UiButton>
          <UiButton variant="danger" size="sm" :disabled="disconnecting" @click="disconnect">
            {{ disconnecting ? 'Disconnecting...' : 'Disconnect' }}
          </UiButton>
        </div>
      </div>
    </div>
  </AppShell>
</template>

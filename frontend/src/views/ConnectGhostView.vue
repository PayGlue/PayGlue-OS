// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import {
  getIntegrationConfig,
  runIntegrationHealthCheck,
  setIntegrationCredentials,
  updateIntegrationConfig,
} from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { IntegrationHealthStatus } from '../types/api'

const session = useSessionStore()

const loading = ref(false)
const saving = ref(false)
const checking = ref(false)
const successMessage = ref<string | null>(null)
const errorMessage = ref<string | null>(null)
const health = ref<IntegrationHealthStatus | null>(null)

const form = reactive({
  contentApiKey: '',
  adminApiKey: '',
  apiUrl: 'http://ghost:2368/ghost/api/admin',
  healthPath: '/site/',
  entitlementsPath: '/members/entitlements/',
})

const getContext = () => {
  if (!session.activeTenantSlug || !session.idToken) {
    throw new Error('Tenant context missing. Please select a tenant first.')
  }
  return { tenantSlug: session.activeTenantSlug, idToken: session.idToken }
}

const loadConnectState = async () => {
  loading.value = true
  errorMessage.value = null

  try {
    const { tenantSlug, idToken } = getContext()
    const config = await getIntegrationConfig(tenantSlug, idToken, 'cms')
    const maybeHealth = config.metadata?.health
    if (maybeHealth && typeof maybeHealth === 'object') {
      const candidate = maybeHealth as Partial<IntegrationHealthStatus>
      if (typeof candidate.ok === 'boolean' && typeof candidate.code === 'string' && typeof candidate.message === 'string') {
        health.value = {
          ok: candidate.ok,
          code: candidate.code,
          message: candidate.message,
          checked_at: typeof candidate.checked_at === 'string' ? candidate.checked_at : new Date().toISOString(),
        }
      }
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to load connect state.'
  } finally {
    loading.value = false
  }
}

const saveGhostConnection = async () => {
  saving.value = true
  successMessage.value = null
  errorMessage.value = null

  try {
    const { tenantSlug, idToken } = getContext()

    const contentApiKey = form.contentApiKey.trim()
    const adminApiKey = form.adminApiKey.trim()
    const apiBaseUrl = form.apiUrl.trim()

    if (!contentApiKey || !adminApiKey || !apiBaseUrl) {
      throw new Error('Content API key, Admin API key, and API URL are required.')
    }

    await updateIntegrationConfig(tenantSlug, idToken, 'cms', {
      enabled: true,
      provider_type: 'ghost',
      metadata: {},
    })

    const credentials: Record<string, string> = {
      content_api_key: contentApiKey,
      admin_api_key: adminApiKey,
      api_base_url: apiBaseUrl,
    }

    const healthPath = form.healthPath.trim()
    const entitlementsPath = form.entitlementsPath.trim()
    if (healthPath) credentials.health_path = healthPath
    if (entitlementsPath) credentials.entitlements_path = entitlementsPath

    await setIntegrationCredentials(tenantSlug, idToken, 'cms', credentials)
    successMessage.value = 'Ghost credentials saved. Run health check next.'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to save Ghost credentials.'
  } finally {
    saving.value = false
  }
}

const runGhostHealthCheck = async () => {
  checking.value = true
  successMessage.value = null
  errorMessage.value = null

  try {
    const { tenantSlug, idToken } = getContext()
    health.value = await runIntegrationHealthCheck(tenantSlug, idToken, 'cms')
    if (health.value.ok) {
      successMessage.value = 'Health check successful. Ghost connection is active.'
    } else {
      errorMessage.value = `${health.value.code}: ${health.value.message}`
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Health check failed.'
  } finally {
    checking.value = false
  }
}

onMounted(async () => {
  await loadConnectState()
})
</script>

<template>
  <AppShell>
    <div class="space-y-6">
      <section class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <p class="text-xs font-semibold uppercase tracking-[0.12em] text-blue-600">Connect Ghost</p>
        <h1 class="mt-1 text-xl font-semibold text-slate-900">Ghost CMS credentials</h1>
        <p class="mt-2 text-sm text-slate-600">Configure Ghost keys so PayGlue can validate health and apply entitlement updates.</p>
      </section>

      <section class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="grid gap-4 md:grid-cols-2">
          <label class="text-sm text-slate-700 md:col-span-2">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Ghost Content API key</span>
            <input
              v-model="form.contentApiKey"
              type="text"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
              placeholder="required"
            />
          </label>

          <label class="text-sm text-slate-700 md:col-span-2">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Ghost Admin API key</span>
            <input
              v-model="form.adminApiKey"
              type="text"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
              placeholder="&lt;id&gt;:&lt;hex-secret&gt;"
            />
          </label>

          <label class="text-sm text-slate-700 md:col-span-2">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Ghost API URL</span>
            <input
              v-model="form.apiUrl"
              type="text"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
              placeholder="http://ghost:2368/ghost/api/admin"
            />
          </label>

          <label class="text-sm text-slate-700">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Health path (optional)</span>
            <input
              v-model="form.healthPath"
              type="text"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
              placeholder="/site/"
            />
          </label>

          <label class="text-sm text-slate-700">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Entitlements path (optional)</span>
            <input
              v-model="form.entitlementsPath"
              type="text"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
              placeholder="/members/entitlements/"
            />
          </label>
        </div>

        <div class="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
            :disabled="saving"
            @click="saveGhostConnection"
          >
            {{ saving ? 'Saving...' : 'Save credentials' }}
          </button>
          <button
            type="button"
            class="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-60"
            :disabled="checking"
            @click="runGhostHealthCheck"
          >
            {{ checking ? 'Checking...' : 'Run health check' }}
          </button>
        </div>

        <p v-if="loading" class="mt-3 text-sm text-slate-500">Loading current state...</p>
        <p v-if="successMessage" class="mt-3 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {{ successMessage }}
        </p>
        <p v-if="errorMessage" class="mt-3 rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {{ errorMessage }}
        </p>

        <div v-if="health" class="mt-4 rounded-lg bg-slate-50 p-3 text-sm">
          <p class="font-medium text-slate-900">Latest health status</p>
          <p class="text-slate-700">{{ health.code }}: {{ health.message }}</p>
          <p class="text-xs text-slate-500">Checked at {{ health.checked_at }}</p>
        </div>
      </section>
    </div>
  </AppShell>
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import { api, deleteTenant, updateTenant } from '../lib/api'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()
const router = useRouter()

const slugInput = ref('')
const originalSlug = ref('')
const saving = ref(false)
const saveError = ref<string | null>(null)
const confirmWebhooks = ref(false)
const confirmUnderstand = ref(false)

const deleteConfirmSlug = ref('')
const deleteError = ref<string | null>(null)
const deleteLoading = ref(false)
const copied = ref(false)
const deleteEffectsAcknowledged = ref(false)

const copySlug = async () => {
  if (!session.activeTenantSlug) return
  await navigator.clipboard.writeText(session.activeTenantSlug)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

const isOwner = computed(() => session.activeMembership?.role === 'owner')
const slugChanged = computed(() => slugInput.value.trim() !== originalSlug.value)

const slugPattern = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/
const slugValid = computed(() => slugPattern.test(slugInput.value.trim()))
const slugAvailable = ref<boolean | null>(null)
const checkingSlug = ref(false)
let checkTimeout: ReturnType<typeof setTimeout> | null = null

const canSave = computed(() => {
  if (!slugChanged.value) return false
  if (!slugValid.value) return false
  if (slugAvailable.value !== true) return false
  if (!confirmWebhooks.value || !confirmUnderstand.value) return false
  return true
})

onMounted(() => {
  originalSlug.value = session.activeTenantSlug ?? ''
  slugInput.value = originalSlug.value
})

watch(() => session.activeTenantSlug, (v) => {
  if (v && !slugChanged.value) {
    originalSlug.value = v
    slugInput.value = v
  }
})

watch(slugInput, (val) => {
  const trimmed = val.trim()
  if (trimmed === originalSlug.value) {
    slugAvailable.value = null
    return
  }
  slugAvailable.value = null
  if (!slugPattern.test(trimmed)) return
  if (checkTimeout) clearTimeout(checkTimeout)
  checkingSlug.value = true
  checkTimeout = setTimeout(async () => {
    try {
      const { data } = await api.get<{ available: boolean }>(
        `/api/v1/tenants/slug-check?slug=${encodeURIComponent(trimmed)}`,
        { headers: { Authorization: `Bearer ${session.idToken}` } },
      )
      slugAvailable.value = data.available
    } catch {
      slugAvailable.value = null
    }
    checkingSlug.value = false
  }, 400)
})

const saveSlug = async () => {
  if (!canSave.value || !session.idToken) return
  const newSlug = slugInput.value.trim()
  if (!slugPattern.test(newSlug)) {
    saveError.value = 'Slug must use lowercase letters, numbers, and hyphens only.'
    return
  }
  saving.value = true
  saveError.value = null
  try {
    const result = await updateTenant(originalSlug.value, session.idToken, { slug: newSlug })
    localStorage.setItem(`payglue:pending-rename:${result.slug}`, '1')
    const idx = session.memberships.findIndex(m => m.tenant_slug === originalSlug.value)
    const membership = idx !== -1 ? session.memberships[idx] : undefined
    if (membership) membership.tenant_slug = result.slug
    session.setActiveTenant(result.slug)
    originalSlug.value = result.slug
    slugInput.value = result.slug
    confirmWebhooks.value = false
    confirmUnderstand.value = false
    await router.replace(`/t/${result.slug}/organization`)
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : 'Could not update slug.'
  } finally {
    saving.value = false
  }
}

const deleteOrg = async () => {
  const slug = session.activeTenantSlug
  if (!slug || !session.idToken) return
  if (deleteConfirmSlug.value !== slug) {
    deleteError.value = 'Publication name does not match.'
    return
  }
  deleteLoading.value = true
  deleteError.value = null
  try {
    await deleteTenant(slug, session.idToken)
    const remaining = session.memberships.filter(m => m.tenant_slug !== slug)
    session.memberships.splice(0, session.memberships.length, ...remaining)
    deleteEffectsAcknowledged.value = false
    const next = remaining[0]
    if (next) {
      session.setActiveTenant(next.tenant_slug)
      await router.push(`/t/${next.tenant_slug}/dashboard`)
    } else {
      await router.push('/tenant/create')
    }
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : 'Could not delete publication.'
  } finally {
    deleteLoading.value = false
  }
}
</script>

<template>
  <AppShell>
    <div class="space-y-6">
      <!-- Slug settings -->
      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">Publication</h1>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Your publication identifier. Changing the slug updates all webhook URLs.</p>

        <!-- Two-column layout when slug changed: input left, warning right -->
        <div class="mt-4" :class="slugChanged ? 'grid grid-cols-1 gap-6 lg:grid-cols-2' : ''">
          <!-- Left: slug input + availability -->
          <div>
            <div class="max-w-sm lg:max-w-none">
              <label class="block">
                <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Slug (URL identifier)</span>
                <input
                  v-model="slugInput"
                  type="text"
                  :disabled="!isOwner"
                  class="w-full rounded-lg border px-3 py-2 text-sm font-mono transition-colors"
                  :class="slugChanged ? 'border-amber-400 bg-amber-50 dark:bg-amber-500/10 focus:outline-none focus:ring-1 focus:ring-amber-400' : 'border-slate-300 dark:border-slate-700'"
                />
              </label>
              <p class="mt-1 text-xs text-slate-400 dark:text-slate-500">Lowercase letters, numbers, hyphens only.</p>
            </div>

            <!-- Slug availability indicator -->
            <div v-if="slugChanged" class="mt-2 max-w-sm lg:max-w-none">
              <div
                class="flex items-center justify-between rounded-lg border px-3 py-2 text-sm font-mono"
                :class="checkingSlug ? 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 text-slate-400 dark:text-slate-500'
                  : !slugValid ? 'border-rose-200 dark:border-rose-500/30 bg-rose-50 dark:bg-rose-500/10 text-slate-500 dark:text-slate-400'
                  : slugAvailable === true ? 'border-emerald-300 bg-emerald-50 dark:bg-emerald-500/10 text-slate-700 dark:text-slate-200'
                  : slugAvailable === false ? 'border-rose-300 bg-rose-50 dark:bg-rose-500/10 text-slate-700 dark:text-slate-200'
                  : 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 text-slate-400 dark:text-slate-500'"
              >
                <span>app.payglue.io/t/<strong>{{ slugInput.trim() }}</strong></span>
                <span v-if="checkingSlug" class="text-xs text-slate-400 dark:text-slate-500">Checking...</span>
                <span v-else-if="!slugValid" class="text-xs font-semibold text-rose-500">Invalid</span>
                <span v-else-if="slugAvailable === true" class="text-xs font-semibold text-emerald-600 dark:text-emerald-400">Available</span>
                <span v-else-if="slugAvailable === false" class="text-xs font-semibold text-rose-500">Taken</span>
              </div>
            </div>
          </div>

          <!-- Right: warning box -- only when slug changed -->
          <div v-if="slugChanged" class="rounded-xl border-2 border-amber-400 bg-amber-50 dark:bg-amber-500/10 p-4">
            <div class="flex items-start gap-3">
              <svg class="mt-0.5 h-5 w-5 shrink-0 text-amber-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
              <div class="flex-1">
                <p class="font-semibold text-amber-900 dark:text-amber-200">Slug change affects all webhook URLs</p>
                <p class="mt-1 text-sm text-amber-800 dark:text-amber-300">
                  After saving, the webhook URL changes for every connected payment provider. You must update the URL in each provider's dashboard manually. Otherwise incoming webhooks will fail and members won't receive access.
                </p>
                <div class="mt-2 rounded bg-amber-100 px-3 py-1.5 font-mono text-xs text-amber-900 dark:text-amber-200">
                  https://api.payglue.io/webhooks/{provider}?tenant=<strong>{{ slugInput.trim() }}</strong>
                </div>
                <div class="mt-3 space-y-2">
                  <label class="flex items-start gap-2 cursor-pointer">
                    <input v-model="confirmWebhooks" type="checkbox" class="mt-0.5 h-4 w-4 accent-amber-600" />
                    <span class="text-sm text-amber-900 dark:text-amber-200">I know I must update the webhook URL at every connected payment provider after saving.</span>
                  </label>
                  <label class="flex items-start gap-2 cursor-pointer">
                    <input v-model="confirmUnderstand" type="checkbox" class="mt-0.5 h-4 w-4 accent-amber-600" />
                    <span class="text-sm text-amber-900 dark:text-amber-200">I understand that webhooks sent to the old URL will fail until I update the provider settings.</span>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>

        <p v-if="saveError" class="mt-3 text-sm text-rose-700 dark:text-rose-300">{{ saveError }}</p>

        <div class="mt-4 flex gap-2">
          <button
            type="button"
            class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="!canSave || saving || !isOwner"
            @click="saveSlug"
          >
            {{ saving ? 'Saving...' : 'Save changes' }}
          </button>
          <button v-if="slugChanged" type="button" class="rounded-lg border border-slate-300 dark:border-slate-700 px-4 py-2 text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40" @click="slugInput = originalSlug; confirmWebhooks = false; confirmUnderstand = false">
            Discard
          </button>
        </div>
      </section>

      <!-- Danger Zone -->
      <section v-if="isOwner" class="rounded-2xl border border-rose-200 dark:border-rose-500/30 bg-white p-5 shadow-sm dark:border-rose-500/30 dark:bg-slate-900">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-rose-600 dark:text-rose-400">Danger zone</h2>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Permanently delete this publication and all associated data including credentials, mappings, and webhook history. This cannot be undone.</p>

        <!-- Step 1: effects acknowledgement -->
        <div v-if="!deleteEffectsAcknowledged" class="space-y-3">
          <div class="rounded-xl border border-rose-200 dark:border-rose-500/30 bg-rose-50 dark:bg-rose-500/10 p-4 text-sm text-rose-900">
            <p class="font-semibold mb-2">This will permanently delete:</p>
            <ul class="space-y-1 list-disc list-inside text-rose-800 dark:text-rose-300">
              <li>All credentials (Ghost Admin API key, provider secrets)</li>
              <li>All mappings and their configuration</li>
              <li>The complete webhook event history</li>
              <li>All publication settings and team member access</li>
            </ul>
            <p class="mt-2 font-medium">This cannot be undone.</p>
          </div>
          <button
            type="button"
            class="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 dark:text-rose-300 hover:bg-rose-50 transition-colors"
            @click="deleteEffectsAcknowledged = true"
          >
            I have read and understand these effects
          </button>
        </div>

        <!-- Step 2: confirm by typing slug -->
        <div v-else class="space-y-3">
          <label class="block text-xs font-medium text-slate-700 dark:text-slate-200">
            Type
            <button
              type="button"
              class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono font-semibold text-slate-900 dark:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              :title="copied ? 'Copied!' : 'Copy to clipboard'"
              @click="copySlug"
            >
              {{ session.activeTenantSlug }}
              <svg v-if="!copied" class="h-3.5 w-3.5 text-slate-400 dark:text-slate-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
              </svg>
              <svg v-else class="h-3.5 w-3.5 text-emerald-500" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
              </svg>
            </button>
            to confirm
          </label>
          <input
            v-model="deleteConfirmSlug"
            type="text"
            :placeholder="session.activeTenantSlug ?? ''"
            class="w-full max-w-sm rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm font-mono outline-none focus:border-rose-400 focus:ring-1 focus:ring-rose-200"
          />
          <p v-if="deleteError" class="text-xs text-rose-600 dark:text-rose-400">{{ deleteError }}</p>
          <div class="flex flex-wrap items-center gap-3 pt-1">
            <button
              type="button"
              class="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="deleteConfirmSlug !== session.activeTenantSlug || deleteLoading"
              @click="deleteOrg"
            >
              {{ deleteLoading ? 'Deleting...' : 'Delete publication' }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-slate-300 dark:border-slate-600 px-4 py-2 text-sm font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              @click="deleteEffectsAcknowledged = false; deleteConfirmSlug = ''"
            >
              Cancel
            </button>
          </div>
        </div>
      </section>
    </div>
  </AppShell>
</template>

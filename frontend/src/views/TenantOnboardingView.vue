// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { supabase } from '../lib/supabase'
import { api, createTenant, updateIntegrationConfig, setIntegrationCredentials } from '../lib/api'
import { isPlanLimitError, planKeyFromError } from '../lib/planUpgrade'
import PayGlueLogo from '../components/PayGlueLogo.vue'
import UpgradeBanner from '../components/UpgradeBanner.vue'

const session = useSessionStore()
const router = useRouter()
const route = useRoute()

const initialStep = Number(route.query.step) as 1 | 2 | 3
const step = ref<1 | 2 | 3>([1, 2, 3].includes(initialStep) ? initialStep : 1)

// Step 1: Publication
const orgName = ref('')
const slugAvailable = ref<boolean | null>(null)
const checkingSlug = ref(false)
const isCreating = ref(false)
const createError = ref<string | null>(null)
const createErrorPlan = ref<string | null>(null)

const slug = computed(() =>
  orgName.value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-|-$/g, ''),
)

const slugValid = computed(() => slug.value.length >= 3)

let checkTimeout: ReturnType<typeof setTimeout> | null = null

watch(slug, (val) => {
  slugAvailable.value = null
  if (!val || val.length < 3) return
  if (checkTimeout) clearTimeout(checkTimeout)
  checkingSlug.value = true
  checkTimeout = setTimeout(async () => {
    try {
      const { data } = await api.get<{ available: boolean }>(
        `/api/v1/tenants/slug-check?slug=${encodeURIComponent(val)}`,
        { headers: { Authorization: `Bearer ${session.idToken}` } },
      )
      slugAvailable.value = data.available
    } catch {
      slugAvailable.value = null
    }
    checkingSlug.value = false
  }, 400)
})

const canProceed = computed(() => slugValid.value && slugAvailable.value === true)

const createOrg = async () => {
  if (!canProceed.value || isCreating.value) return
  isCreating.value = true
  createError.value = null
  createErrorPlan.value = null

  const { data: { user } } = await supabase.auth.getUser()
  if (!user) { createError.value = 'Not authenticated.'; isCreating.value = false; return }

  const { error } = await supabase.from('tenants').insert({
    slug: slug.value,
    name: orgName.value.trim(),
    owner_id: user.id,
  })

  if (error) {
    createError.value = error.message
    isCreating.value = false
    return
  }

  await supabase.from('tenant_members').insert({
    tenant_id: (await supabase.from('tenants').select('id').eq('slug', slug.value).single()).data?.id,
    user_id: user.id,
    role: 'owner',
  })

  const { data: { session: authSession } } = await supabase.auth.getSession()
  if (!authSession?.access_token) {
    createError.value = 'Session lost. Please reload and try again.'
    isCreating.value = false
    return
  }

  try {
    await createTenant(authSession.access_token, { slug: slug.value })
  } catch (err) {
    const isAlreadyExists =
      err instanceof Error && err.message.toLowerCase().includes('already exists')
    if (!isAlreadyExists) {
      const status = (err as { status?: number })?.status
      if (isPlanLimitError(err)) {
        createError.value = err.message
        createErrorPlan.value = planKeyFromError(err)
      } else {
        createError.value = `Backend sync failed [${status ?? '?'}]: ${err instanceof Error ? err.message : String(err)}`
        createErrorPlan.value = null
      }
      isCreating.value = false
      return
    }
  }

  await session.bootstrap()
  session.setActiveTenant(slug.value)
  step.value = 2
  isCreating.value = false
}

// Step 2: Connect Ghost
const ghostUrl = ref('')
const contentKey = ref('')
const adminKey = ref('')
const isSavingGhost = ref(false)
const ghostError = ref<string | null>(null)
const ghostSaved = ref(false)

const DEV_GHOST_URL = 'https://dev.example.com'
const DEV_CONTENT_KEY = 'acac4d839f6cfa04b907a04cf4deadbeef'
const DEV_ADMIN_KEY = '6a3145b0e72c430001fdcd39:f0533b2bdeadbeefdeadbeefdeadbeef'

const applyDevShortcut = () => {
  ghostUrl.value = DEV_GHOST_URL
  contentKey.value = DEV_CONTENT_KEY
  adminKey.value = DEV_ADMIN_KEY
}

const canSaveGhost = computed(() =>
  ghostUrl.value.trim().startsWith('http') &&
  contentKey.value.trim().length > 10 &&
  adminKey.value.trim().includes(':'),
)

const isDevMode = computed(() =>
  ghostUrl.value.trim() === DEV_GHOST_URL &&
  contentKey.value.trim() === DEV_CONTENT_KEY &&
  adminKey.value.trim() === DEV_ADMIN_KEY,
)

watch([ghostUrl, contentKey, adminKey], ([url, content, admin]) => {
  if (url.trim() === 'x' || content.trim() === 'x' || admin.trim() === 'x') {
    applyDevShortcut()
  }
})

const saveGhost = async () => {
  if (!canSaveGhost.value || isSavingGhost.value) return
  isSavingGhost.value = true
  ghostError.value = null
  try {
    if (isDevMode.value) {
      // Dev shortcut: skip real API call
      localStorage.setItem(`payglue:ghost:${slug.value}`, JSON.stringify({ url: DEV_GHOST_URL }))
      ghostSaved.value = true
      setTimeout(() => { step.value = 3 }, 600)
      return
    }
    const idToken = session.idToken
    if (!idToken) throw new Error('Not authenticated.')
    await updateIntegrationConfig(slug.value, idToken, 'cms', {
      enabled: true,
      provider_type: 'ghost',
      metadata: {},
    })
    await setIntegrationCredentials(slug.value, idToken, 'cms', {
      api_base_url: ghostUrl.value.trim(),
      content_api_key: contentKey.value.trim(),
      admin_api_key: adminKey.value.trim(),
    })
    localStorage.setItem(`payglue:ghost:${slug.value}`, JSON.stringify({ url: ghostUrl.value.trim() }))
    ghostSaved.value = true
    setTimeout(() => { step.value = 3 }, 600)
  } catch (err) {
    ghostError.value = err instanceof Error ? err.message : 'Failed to save Ghost credentials.'
  } finally {
    isSavingGhost.value = false
  }
}

const skipGhost = () => { step.value = 3 }

// Step 3: Payment provider
const providers = [
  {
    key: 'polar',
    name: 'Polar',
    description: 'Modern payments for developers. Built-in subscriptions, one-time purchases, and license keys.',
    status: 'available' as const,
  },
  {
    key: 'paypal',
    name: 'PayPal',
    description: 'Widely trusted payment platform, available in 200+ countries and markets.',
    status: 'available' as const,
  },
  {
    key: 'mollie',
    name: 'Mollie',
    description: 'European payment provider with support for cards, SEPA, iDEAL, and more. Hosted in the EU.',
    status: 'planned' as const,
  },
  {
    key: 'paddle',
    name: 'Paddle',
    description: 'Merchant of record solution with built-in tax and compliance handling.',
    status: 'available' as const,
  },
  {
    key: 'gumroad',
    name: 'Gumroad',
    description: 'Simple digital product sales for creators.',
    status: 'available' as const,
  },
  {
    key: 'lemonsqueezy',
    name: 'Lemon Squeezy',
    description: 'All-in-one payments, subscriptions, and digital products platform.',
    status: 'available' as const,
  },
  {
    key: 'kofi',
    name: 'Ko-fi',
    description: 'Popular in the Ghost community for tips and memberships. No dashboard API to auto-fetch products.',
    status: 'available' as const,
  },
  {
    key: 'patreon',
    name: 'Patreon',
    description: 'Membership platform for creators. Map your Patreon tiers to Ghost access levels.',
    status: 'available' as const,
  },
  {
    key: 'creem',
    name: 'Creem',
    description: 'Modern checkout with built-in subscriptions and license keys.',
    status: 'available' as const,
  },
  {
    key: 'stripe',
    name: 'Stripe',
    description: 'The gold standard for online payments. Full control, maximum flexibility.',
    status: 'visible' as const,
  },
]

const selectedProvider = ref<string | null>(null)

const goToDashboard = () => {
  if (selectedProvider.value) {
    localStorage.setItem(`payglue:provider:${slug.value}`, selectedProvider.value)
  }
  if (selectedProvider.value === 'polar') {
    router.push(`/t/${slug.value}/connection/polar`)
    return
  }
  if (selectedProvider.value === 'lemonsqueezy') {
    router.push(`/t/${slug.value}/connection/lemonsqueezy`)
    return
  }
  const tyKey = `pg_ty_${slug.value}`
  if (!localStorage.getItem(tyKey)) {
    router.push(`/t/${slug.value}/thank-you`)
  } else {
    router.push(`/t/${slug.value}/integrations`)
  }
}

const skipProvider = () => router.push(`/t/${slug.value}/dashboard`)
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
    <section class="w-full max-w-lg">

      <!-- Logo -->
      <div class="mb-8 text-center">
        <RouterLink to="/"><PayGlueLogo size="lg" /></RouterLink>
      </div>

      <!-- Progress -->
      <div class="mb-8 flex items-center gap-2">
        <div class="flex items-center gap-2">
          <span class="flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
            :class="step >= 1 ? 'bg-indigo-600 text-white' : 'bg-slate-200 text-slate-500'">1</span>
          <span class="text-sm font-medium" :class="step >= 1 ? 'text-slate-900' : 'text-slate-400'">Publication</span>
        </div>
        <div class="h-px flex-1 bg-slate-200"></div>
        <div class="flex items-center gap-2">
          <span class="flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
            :class="step >= 2 ? 'bg-indigo-600 text-white' : 'bg-slate-200 text-slate-500'">2</span>
          <span class="text-sm font-medium" :class="step >= 2 ? 'text-slate-900' : 'text-slate-400'">Ghost</span>
        </div>
        <div class="h-px flex-1 bg-slate-200"></div>
        <div class="flex items-center gap-2">
          <span class="flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
            :class="step >= 3 ? 'bg-indigo-600 text-white' : 'bg-slate-200 text-slate-500'">3</span>
          <span class="text-sm font-medium" :class="step >= 3 ? 'text-slate-900' : 'text-slate-400'">Payment</span>
        </div>
      </div>

      <!-- Step 1 -->
      <div v-if="step === 1" class="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <p class="text-xs font-semibold uppercase tracking-widest text-indigo-500">Step 1 of 3</p>
        <h1 class="mt-2 text-xl font-bold text-slate-900">Create your publication</h1>
        <p class="mt-1 text-sm text-slate-500">
          A publication groups your Ghost blog, team members, and payment mappings. You can have multiple.
        </p>

        <div class="mt-6">
          <label class="block text-xs font-semibold uppercase tracking-wide text-slate-500">Publication name</label>
          <input
            v-model="orgName"
            type="text"
            placeholder="Acme Media"
            class="mt-1.5 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />

          <div v-if="slug" class="mt-3 flex items-center justify-between rounded-lg border px-3 py-2"
            :class="checkingSlug ? 'border-slate-200 bg-slate-50' : slugAvailable === true ? 'border-emerald-200 bg-emerald-50' : slugAvailable === false ? 'border-rose-200 bg-rose-50' : 'border-slate-200 bg-slate-50'">
            <span class="font-mono text-xs text-slate-500">app.payglue.io/t/<strong class="text-slate-700">{{ slug }}</strong></span>
            <span v-if="checkingSlug" class="text-xs text-slate-400">Checking...</span>
            <span v-else-if="slugAvailable === true" class="text-xs font-semibold text-emerald-600">Available</span>
            <span v-else-if="slugAvailable === false" class="text-xs font-semibold text-rose-600">Taken</span>
          </div>
        </div>

        <UpgradeBanner v-if="createError && createErrorPlan" class="mt-3" :message="createError" :plan-key="createErrorPlan" />
        <p v-else-if="createError" class="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{{ createError }}</p>

        <button
          class="mt-6 w-full rounded-xl bg-indigo-600 py-3 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-40"
          :disabled="!canProceed || isCreating"
          @click="createOrg"
        >
          {{ isCreating ? 'Creating...' : 'Continue' }}
        </button>
      </div>

      <!-- Step 2 -->
      <div v-else-if="step === 2" class="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <p class="text-xs font-semibold uppercase tracking-widest text-indigo-500">Step 2 of 3</p>
        <h1 class="mt-2 text-xl font-bold text-slate-900">Connect your Ghost blog</h1>
        <p class="mt-1 text-sm text-slate-500">
          PayGlue needs API access to sync memberships. Follow these steps in your Ghost admin.
        </p>

        <div class="mt-6 space-y-4">
          <div class="rounded-xl border border-slate-100 bg-slate-50 p-4">
            <p class="text-xs font-bold uppercase tracking-widest text-slate-400">Step 1</p>
            <p class="mt-1 text-sm font-semibold text-slate-900">Open Ghost Settings</p>
            <p class="mt-0.5 text-sm text-slate-500">
              In your Ghost admin, click <strong>Settings</strong> in the left sidebar.
            </p>
          </div>

          <div class="rounded-xl border border-slate-100 bg-slate-50 p-4">
            <p class="text-xs font-bold uppercase tracking-widest text-slate-400">Step 2</p>
            <p class="mt-1 text-sm font-semibold text-slate-900">Go to Advanced → Integrations</p>
            <p class="mt-0.5 text-sm text-slate-500">
              Scroll down to <strong>Advanced</strong>, then click <strong>Integrations</strong>.
            </p>
          </div>

          <div class="rounded-xl border border-slate-100 bg-slate-50 p-4">
            <p class="text-xs font-bold uppercase tracking-widest text-slate-400">Step 3</p>
            <p class="mt-1 text-sm font-semibold text-slate-900">Add custom integration</p>
            <p class="mt-0.5 text-sm text-slate-500">
              Click <strong>+ Add custom integration</strong>, name it <strong>PayGlue</strong>, and confirm.
              You will see a <strong>Content API key</strong> and an <strong>Admin API key</strong>. Copy both.
            </p>
          </div>
        </div>

        <div class="mt-6 space-y-3">
          <div>
            <label class="block text-xs font-semibold uppercase tracking-wide text-slate-500">Content API Key</label>
            <input
              v-model="contentKey"
              type="text"
              placeholder="acac4d839f6cfa04b907a04cf4..."
              autocomplete="off"
              class="mt-1.5 w-full rounded-xl border border-slate-300 px-4 py-3 font-mono text-sm text-slate-900 placeholder-slate-400 placeholder:font-sans focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />
          </div>
          <div>
            <label class="block text-xs font-semibold uppercase tracking-wide text-slate-500">Admin API Key</label>
            <input
              v-model="adminKey"
              type="text"
              placeholder="6a3145b0e72c430001fdcd39:f0533b2b..."
              autocomplete="off"
              class="mt-1.5 w-full rounded-xl border border-slate-300 px-4 py-3 font-mono text-sm text-slate-900 placeholder-slate-400 placeholder:font-sans focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />
            <p class="mt-1 text-xs text-slate-400">Format: <code class="rounded bg-slate-100 px-1">id:hex-secret</code></p>
          </div>
          <div>
            <label class="block text-xs font-semibold uppercase tracking-wide text-slate-500">Ghost URL</label>
            <input
              v-model="ghostUrl"
              type="text"
              placeholder="https://www.yourblog.com"
              class="mt-1.5 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />
          </div>
        </div>

        <p v-if="ghostError" class="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{{ ghostError }}</p>

        <div class="mt-4 flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 flex-shrink-0 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          <p class="text-xs text-slate-500">Your credentials are encrypted at rest, stored in the EU, and never shared with third parties.</p>
        </div>

        <div class="mt-4 flex gap-3">
          <button
            class="flex-1 rounded-xl bg-indigo-600 py-3 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-40"
            :disabled="!canSaveGhost || isSavingGhost || ghostSaved"
            @click="saveGhost"
          >
            {{ ghostSaved ? 'Connected!' : isSavingGhost ? 'Saving...' : 'Connect Ghost' }}
          </button>
          <button
            class="rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-500 transition-colors hover:bg-slate-50"
            @click="skipGhost"
          >
            Skip for now
          </button>
        </div>
      </div>

      <!-- Step 3 -->
      <div v-else class="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <p class="text-xs font-semibold uppercase tracking-widest text-indigo-500">Step 3 of 3</p>
        <h1 class="mt-2 text-xl font-bold text-slate-900">Choose your payment provider</h1>
        <p class="mt-1 text-sm text-slate-500">
          Select the platform you use to sell memberships or products. You can change this later.
        </p>

        <div class="mt-6 space-y-3">
          <template v-for="provider in providers" :key="provider.key">
            <!-- Stripe hint above Stripe card -->
            <div v-if="provider.key === 'stripe'" class="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3">
              <p class="text-xs font-medium text-blue-800">Stripe not required</p>
              <p class="mt-0.5 text-xs text-blue-700">
                PayGlue works without Stripe. If your Ghost blog is not connected to Stripe, it works in coexistence with your existing memberships.
              </p>
            </div>

            <button
              class="group relative w-full rounded-xl border px-4 py-4 text-left transition-all"
              :class="[
                provider.status === 'planned'
                  ? 'cursor-not-allowed border-slate-100 bg-slate-50 opacity-50'
                  : provider.status === 'visible'
                      ? 'cursor-default border-slate-200 bg-white'
                      : selectedProvider === provider.key
                        ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-500/20'
                        : 'border-slate-200 bg-white hover:border-indigo-300 hover:bg-slate-50'
              ]"
              :disabled="provider.status !== 'available'"
              @click="provider.status === 'available' && (selectedProvider = provider.key)"
            >
              <div class="flex items-start gap-3">
                <span class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white">
                  <svg v-if="provider.key === 'polar'" class="h-5 w-5" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="10" cy="10" r="9" stroke="#111827" stroke-width="1.5"/>
                    <circle cx="10" cy="10" r="5" stroke="#111827" stroke-width="1.5"/>
                  </svg>
                  <svg v-else-if="provider.key === 'mollie'" class="h-5 w-5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="12" cy="12" r="12" fill="#111827"/>
                    <path d="M5.5 8.5h2.3l4.2 4.5 4.2-4.5H18.5v7h-2.2v-4.6l-4 4.3-4-4.3v4.6H5.5V8.5Z" fill="white"/>
                  </svg>
                  <img v-else-if="provider.key === 'creem'" src="https://www.creem.io/icon.png" alt="Creem" class="h-5 w-5" />
                  <img v-else :src="`https://cdn.simpleicons.org/${provider.key}/111827`" :alt="provider.name" class="h-5 w-5" />
                </span>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <span class="text-sm font-semibold" :class="provider.status === 'available' || provider.status === 'visible' ? 'text-slate-900' : 'text-slate-400'">
                      {{ provider.name }}
                    </span>
                    <span v-if="provider.key === 'mollie'" class="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-600">EU</span>
                    <span v-if="provider.status === 'planned'" class="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-500">Planned</span>
                  </div>
                  <p class="mt-0.5 text-xs" :class="provider.status === 'available' || provider.status === 'visible' ? 'text-slate-500' : 'text-slate-400'">
                    {{ provider.description }}
                  </p>
                </div>
                <div v-if="provider.status === 'available'" class="flex-shrink-0 pt-0.5">
                  <div class="flex h-4 w-4 items-center justify-center rounded-full border-2 transition-all"
                    :class="selectedProvider === provider.key ? 'border-indigo-600 bg-indigo-600' : 'border-slate-300'">
                    <div v-if="selectedProvider === provider.key" class="h-1.5 w-1.5 rounded-full bg-white"></div>
                  </div>
                </div>
              </div>
            </button>
          </template>
        </div>

        <div class="mt-6 flex gap-3">
          <button
            class="flex-1 rounded-xl bg-indigo-600 py-3 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-40"
            :disabled="!selectedProvider"
            @click="goToDashboard"
          >
            Set up {{ providers.find(p => p.key === selectedProvider)?.name ?? 'integration' }}
          </button>
          <button
            class="rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-500 transition-colors hover:bg-slate-50"
            @click="skipProvider"
          >
            Skip for now
          </button>
        </div>
      </div>

    </section>
  </div>
</template>

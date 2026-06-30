// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PayGlueLogo from './PayGlueLogo.vue'
import { signOutFromFirebase } from '../lib/firebaseAuth'
import { useSessionStore } from '../stores/session'
import { getGhostStripeStatus, getIntegrationConfig } from '../lib/api'
import { useHeaderScriptStatus } from '../composables/useHeaderScriptStatus'

const session = useSessionStore()
const route = useRoute()
const router = useRouter()
const mobileSidebarOpen = ref(false)
const settingsOpen = ref(false)
const connectionOpen = ref(false)
const installationOpen = ref(false)
const analyticsOpen = ref(false)
const orgDropdownOpen = ref(false)
const accountPopupOpen = ref(false)

const PROVIDERS = [
  { key: 'polar', name: 'Polar', status: 'available' as const },
  { key: 'paypal', name: 'PayPal', status: 'available' as const },
  { key: 'mollie', name: 'Mollie', status: 'deployment' as const },
  { key: 'paddle', name: 'Paddle', status: 'planned' as const },
  { key: 'gumroad', name: 'Gumroad', status: 'planned' as const },
  { key: 'lemonsqueezy', name: 'Lemon Squeezy', status: 'available' as const },
  { key: 'stripe', name: 'Stripe', status: 'deployment' as const },
]


const pageTitles: Record<string, { title: string; description: string }> = {
  dashboard: { title: 'Dashboard', description: 'Track tenant operations, replay health, and team activity.' },
'connection-ghost': { title: 'Ghost CMS', description: 'Connect your Ghost instance and validate the Admin API.' },
  'connection-polar': { title: 'Polar', description: 'Connect Polar webhooks for automatic member sync.' },
  'connection-paypal': { title: 'PayPal', description: 'Connect PayPal webhooks for automatic member sync.' },
  'connection-lemonsqueezy': { title: 'Lemon Squeezy', description: 'Connect Lemon Squeezy webhooks for automatic member sync.' },
  events: { title: 'Webhook Events', description: 'Inspect webhook pipelines and replay outcomes.' },
  mappings: { title: 'Product Mapping', description: 'Overview of all configured product-to-Ghost action mappings.' },
  billing: { title: 'Billing', description: 'Maintain billing profile and invoicing context.' },
  team: { title: 'Team', description: 'Manage members, roles, and tenant permissions.' },
  organization: { title: 'Organization', description: 'Manage your organization identifier and danger zone.' },
  preferences: { title: 'Preferences', description: 'Account and workspace preferences.' },
  installation: { title: 'Installation', description: 'Copy embed snippets and validate hosted pricing render.' },
  pricing: { title: 'Pricing Tables', description: 'Build and embed pricing tables for your Ghost site.' },
}

const settingsItems = computed(() => {
  const slug = session.activeTenantSlug
  if (!slug) return []
  return [
    { label: 'Team', to: `/t/${slug}/team` },
    { label: 'Billing', to: `/t/${slug}/billing` },
    { label: 'Preferences', to: `/t/${slug}/preferences` },
    { label: 'Organization', to: `/t/${slug}/organization` },
  ]
})

const pageMeta = computed(() => {
  const key = String(route.name ?? '')
  return pageTitles[key] ?? { title: 'Control panel', description: 'Manage tenant configuration and operations.' }
})

const isActive = (to: string) => route.path === to
const isUnderConnection = computed(() => route.path.includes('/connection'))
const isUnderAnalytics = computed(() => route.path.includes('/events') || route.path.includes('/mappings'))
const isSettingsActive = computed(() =>
  settingsItems.value.some(item => route.path === item.to)
)

watch(isSettingsActive, (val) => { if (val) settingsOpen.value = true }, { immediate: true })
watch(isUnderConnection, (val) => { if (val) connectionOpen.value = true }, { immediate: true })
watch(isUnderAnalytics, (val) => { if (val) analyticsOpen.value = true }, { immediate: true })
watch(() => route.path, (p) => { if (p.includes('/installation') || p.includes('/paywall') || p.includes('/buttons') || p.includes('/pricing')) installationOpen.value = true }, { immediate: true })

const switchOrg = (tenantSlug: string) => {
  orgDropdownOpen.value = false
  if (tenantSlug === session.activeTenantSlug) return
  session.setActiveTenant(tenantSlug)
  mobileSidebarOpen.value = false
  router.push(`/t/${tenantSlug}/dashboard`)
}

const { isInstalled: headerScriptInstalled } = useHeaderScriptStatus()

const stripeConnected = ref<boolean | null>(null)

const loadStripeStatus = async () => {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  try {
    const config = await getIntegrationConfig(slug, token, 'cms').catch(() => null)
    if (!config?.enabled) return
    const result = await getGhostStripeStatus(slug, token)
    stripeConnected.value = result.connected
  } catch {
    // ignore — badge stays null (no badge shown)
  }
}

onMounted(loadStripeStatus)
watch(() => session.activeTenantSlug, loadStripeStatus)

const signOut = async () => {
  try {
    await signOutFromFirebase()
  } catch {
    // resilient
  }
  mobileSidebarOpen.value = false
  accountPopupOpen.value = false
  session.clearSession()
  await router.push('/login')
}

const accountDisplayName = computed(() => {
  const meta = session.user?.user_metadata ?? {}
  const first = meta.first_name as string | undefined
  if (first?.trim()) return first.trim()
  const email = session.user?.email ?? ''
  return email.split('@')[0] || 'Account'
})

watch(
  () => route.fullPath,
  () => { mobileSidebarOpen.value = false },
)
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-900">
    <div class="flex min-h-screen">

      <!-- Desktop sidebar -->
      <aside class="hidden w-60 shrink-0 flex-col bg-slate-900 md:flex">

        <!-- Logo -->
        <div class="px-4 py-5">
          <PayGlueLogo size="md" :dark="true" />
        </div>

        <!-- Org switcher -->
        <div v-if="session.memberships.length" class="relative px-3 pb-2">
          <div v-if="orgDropdownOpen" class="fixed inset-0 z-10" @click="orgDropdownOpen = false" />
          <button
            class="relative z-20 w-full rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-2 text-left transition-colors hover:border-slate-600"
            @click="orgDropdownOpen = !orgDropdownOpen"
          >
            <div class="flex items-center gap-2">
              <div class="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-indigo-900 text-xs font-semibold text-indigo-300">
                {{ session.activeTenantSlug?.[0]?.toUpperCase() ?? '?' }}
              </div>
              <div class="min-w-0 flex-1">
                <p class="truncate text-xs font-medium text-slate-200">{{ session.activeTenantSlug }}</p>
                <p class="text-[10px] text-slate-500">Personal org</p>
              </div>
              <svg class="h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform" :class="orgDropdownOpen ? 'rotate-180' : ''" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </button>
          <div v-if="orgDropdownOpen" class="absolute left-3 right-3 z-30 mt-1 overflow-hidden rounded-lg border border-slate-700 bg-slate-800 shadow-xl">
            <div
              v-for="m in session.memberships"
              :key="m.tenant_slug"
              class="flex cursor-pointer items-center gap-2 px-3 py-2 transition-colors hover:bg-slate-700"
              @click="switchOrg(m.tenant_slug)"
            >
              <div class="grid h-6 w-6 shrink-0 place-items-center rounded bg-indigo-900 text-[10px] font-semibold text-indigo-300">
                {{ m.tenant_slug[0]?.toUpperCase() }}
              </div>
              <span class="flex-1 truncate text-xs text-slate-300">{{ m.tenant_slug }}</span>
              <svg v-if="m.tenant_slug === session.activeTenantSlug" class="h-3.5 w-3.5 text-indigo-400" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
            </div>
            <div class="border-t border-slate-700">
              <RouterLink
                to="/tenant/create"
                class="flex items-center gap-2 px-3 py-2 text-xs text-slate-500 transition-colors hover:bg-slate-700 hover:text-slate-200"
                @click="orgDropdownOpen = false"
              >
                <svg class="h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
                Add organization
              </RouterLink>
            </div>
          </div>
        </div>

        <!-- Main nav -->
        <nav class="flex-1 space-y-0.5 px-3 py-2">

          <!-- Dashboard -->
          <RouterLink
            v-if="session.activeTenantSlug"
            :to="`/t/${session.activeTenantSlug}/dashboard`"
            class="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors"
            :class="isActive(`/t/${session.activeTenantSlug}/dashboard`) ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
          >
            <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12l8.954-8.955a1.126 1.126 0 011.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
            </svg>
            Dashboard
          </RouterLink>

          <!-- Connection expandable -->
          <button
            v-if="session.activeTenantSlug"
            class="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors"
            :class="isUnderConnection ? 'text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
            @click="connectionOpen = !connectionOpen"
          >
            <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
            </svg>
            <span class="flex-1 text-left">Connection</span>
            <svg class="h-3.5 w-3.5 shrink-0 transition-transform" :class="connectionOpen ? 'rotate-180' : ''" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          <div v-if="connectionOpen && session.activeTenantSlug" class="ml-7 space-y-0.5 border-l border-slate-700 pl-3">
            <!-- Ghost CMS -->
            <RouterLink
              :to="`/t/${session.activeTenantSlug}/connection/ghost`"
              class="block rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="isActive(`/t/${session.activeTenantSlug}/connection/ghost`) ? 'text-indigo-400 font-medium' : 'text-slate-500 hover:text-slate-200'"
            >
              Ghost CMS
            </RouterLink>
            <!-- Payment providers -->
            <template v-for="provider in PROVIDERS" :key="provider.key">
              <RouterLink
                v-if="provider.status === 'available' || provider.key === 'stripe'"
                :to="`/t/${session.activeTenantSlug}/connection/${provider.key}`"
                class="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors text-slate-500 hover:text-slate-200"
                :class="isActive(`/t/${session.activeTenantSlug}/connection/${provider.key}`) ? 'text-indigo-400 font-medium' : ''"
              >
                {{ provider.name }}
                <template v-if="provider.key === 'stripe'">
                  <span
                    v-if="stripeConnected === true"
                    class="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-emerald-900/50 text-emerald-400"
                  >Active</span>
                  <span
                    v-else-if="stripeConnected === false"
                    class="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-amber-900/50 text-amber-400"
                  >Disabled</span>
                </template>
                <span
                  v-else-if="provider.status !== 'available'"
                  class="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-blue-900/50 text-blue-400"
                >
                  Soon
                </span>
              </RouterLink>
              <div v-else class="flex items-center gap-2 rounded-md px-3 py-1.5">
                <span class="text-sm text-slate-600">{{ provider.name }}</span>
                <span
                  class="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                  :class="provider.status === 'deployment' ? 'bg-blue-900/50 text-blue-400' : 'bg-slate-800 text-slate-500'"
                >
                  {{ provider.status === 'deployment' ? 'Soon' : 'Planned' }}
                </span>
              </div>
            </template>
          </div>

          <!-- Installation -->
          <button
            v-if="session.activeTenantSlug"
            class="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors"
            :class="isActive(`/t/${session.activeTenantSlug}/installation`)
              ? 'text-white'
              : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
            @click="installationOpen = !installationOpen"
          >
            <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
            </svg>
            <span class="flex-1 text-left">Installation</span>
            <svg
              class="h-3.5 w-3.5 shrink-0 transition-transform"
              :class="installationOpen ? 'rotate-180' : ''"
              fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          <div v-if="installationOpen && session.activeTenantSlug" class="ml-7 space-y-0.5 border-l border-slate-700 pl-3">
            <RouterLink
              :to="`/t/${session.activeTenantSlug}/buttons`"
              class="block rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="isActive(`/t/${session.activeTenantSlug}/buttons`) ? 'text-indigo-400 font-medium' : 'text-slate-500 hover:text-slate-200'"
            >
              Buttons
            </RouterLink>
            <RouterLink
              :to="`/t/${session.activeTenantSlug}/paywall`"
              class="block rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="isActive(`/t/${session.activeTenantSlug}/paywall`) ? 'text-indigo-400 font-medium' : 'text-slate-500 hover:text-slate-200'"
            >
              Paywall
            </RouterLink>
            <RouterLink
              :to="`/t/${session.activeTenantSlug}/pricing`"
              class="block rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="isActive(`/t/${session.activeTenantSlug}/pricing`) ? 'text-indigo-400 font-medium' : 'text-slate-500 hover:text-slate-200'"
            >
              Pricing Table
            </RouterLink>
            <RouterLink
              :to="`/t/${session.activeTenantSlug}/installation`"
              class="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="isActive(`/t/${session.activeTenantSlug}/installation`) ? 'text-indigo-400 font-medium' : 'text-slate-500 hover:text-slate-200'"
            >
              Header script
              <span
                v-if="headerScriptInstalled"
                class="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-emerald-900/50 text-emerald-400"
              >Enabled</span>
              <span
                v-else
                class="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-amber-900/50 text-amber-400"
              >Disabled</span>
            </RouterLink>
          </div>

          <!-- Analytics expandable -->
          <button
            v-if="session.activeTenantSlug"
            class="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors"
            :class="isUnderAnalytics ? 'text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
            @click="analyticsOpen = !analyticsOpen"
          >
            <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3 12h3l3-9 4 18 3-9h5" />
            </svg>
            <span class="flex-1 text-left">Analytics</span>
            <svg
              class="h-3.5 w-3.5 shrink-0 transition-transform"
              :class="analyticsOpen ? 'rotate-180' : ''"
              fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          <div v-if="analyticsOpen && session.activeTenantSlug" class="ml-7 space-y-0.5 border-l border-slate-700 pl-3">
            <RouterLink
              :to="`/t/${session.activeTenantSlug}/events`"
              class="block rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="isActive(`/t/${session.activeTenantSlug}/events`) ? 'text-indigo-400 font-medium' : 'text-slate-500 hover:text-slate-200'"
            >
              Webhook Events
            </RouterLink>
            <RouterLink
              :to="`/t/${session.activeTenantSlug}/mappings`"
              class="block rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="isActive(`/t/${session.activeTenantSlug}/mappings`) ? 'text-indigo-400 font-medium' : 'text-slate-500 hover:text-slate-200'"
            >
              Product Mapping
            </RouterLink>
          </div>

          <!-- Settings expandable -->
          <button
            class="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors"
            :class="isSettingsActive
              ? 'text-white'
              : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
            @click="settingsOpen = !settingsOpen"
          >
            <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span class="flex-1 text-left">Settings</span>
            <svg
              class="h-3.5 w-3.5 shrink-0 transition-transform"
              :class="settingsOpen ? 'rotate-180' : ''"
              fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          <!-- Settings submenu -->
          <div v-if="settingsOpen" class="ml-7 space-y-0.5 border-l border-slate-700 pl-3">
            <RouterLink
              v-for="item in settingsItems"
              :key="item.to"
              :to="item.to"
              class="block rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="isActive(item.to)
                ? 'text-indigo-400 font-medium'
                : 'text-slate-500 hover:text-slate-200'"
            >
              {{ item.label }}
            </RouterLink>
          </div>
        </nav>

        <!-- Bottom utility links -->
        <div class="border-t border-slate-800 px-3 py-3 space-y-0.5">
          <a
            href="mailto:team@payglue.io"
            class="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-slate-500 transition-colors hover:bg-slate-800 hover:text-slate-200"
          >
            <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
            </svg>
            Support
          </a>
          <a
            href="https://docs.payglue.io"
            target="_blank"
            rel="noopener"
            class="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-slate-500 transition-colors hover:bg-slate-800 hover:text-slate-200"
          >
            <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
            </svg>
            Documentation
          </a>
        </div>

        <!-- Account row with popup -->
        <div class="relative border-t border-slate-800 px-3 py-3">
          <div v-if="accountPopupOpen" class="fixed inset-0 z-10" @click="accountPopupOpen = false" />

          <!-- Slide-up popup -->
          <Transition
            enter-active-class="transition duration-150 ease-out"
            enter-from-class="translate-y-2 opacity-0"
            enter-to-class="translate-y-0 opacity-100"
            leave-active-class="transition duration-100 ease-in"
            leave-from-class="translate-y-0 opacity-100"
            leave-to-class="translate-y-2 opacity-0"
          >
            <div
              v-if="accountPopupOpen"
              class="absolute bottom-full left-3 right-3 z-20 mb-2 overflow-hidden rounded-xl border border-slate-700 bg-slate-800 shadow-2xl"
            >
              <!-- User info header -->
              <div class="border-b border-slate-700 px-4 py-3">
                <div class="flex items-center gap-3">
                  <div class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-indigo-600/30 text-sm font-semibold text-indigo-400">
                    {{ accountDisplayName.charAt(0).toUpperCase() }}
                  </div>
                  <div class="min-w-0">
                    <p class="truncate text-sm font-medium text-slate-200">{{ accountDisplayName }}</p>
                    <p class="truncate text-xs text-slate-500">{{ session.user?.email }}</p>
                  </div>
                </div>
              </div>
              <!-- Actions -->
              <div class="p-1">
                <RouterLink
                  v-if="session.activeTenantSlug"
                  :to="`/t/${session.activeTenantSlug}/organization`"
                  class="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-slate-300 transition-colors hover:bg-slate-700 hover:text-white"
                  @click="accountPopupOpen = false"
                >
                  <svg class="h-4 w-4 shrink-0 text-slate-500" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21" />
                  </svg>
                  Organization
                </RouterLink>
                <RouterLink
                  to="/tenant/create"
                  class="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-slate-300 transition-colors hover:bg-slate-700 hover:text-white"
                  @click="accountPopupOpen = false"
                >
                  <svg class="h-4 w-4 shrink-0 text-slate-500" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                  New Organization
                </RouterLink>
                <div class="my-1 border-t border-slate-700" />
                <button
                  class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-rose-400 transition-colors hover:bg-slate-700 hover:text-rose-300"
                  @click="signOut"
                >
                  <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
                  </svg>
                  Sign out
                </button>
              </div>
            </div>
          </Transition>

          <!-- Trigger button -->
          <button
            class="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-slate-800"
            @click="accountPopupOpen = !accountPopupOpen"
          >
            <div class="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-indigo-600/20 text-xs font-semibold text-indigo-400">
              {{ accountDisplayName.charAt(0).toUpperCase() }}
            </div>
            <p class="min-w-0 flex-1 truncate text-left text-xs text-slate-400">{{ accountDisplayName }}</p>
            <svg class="h-3.5 w-3.5 shrink-0 text-slate-600 transition-transform" :class="accountPopupOpen ? 'rotate-180' : ''" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </aside>

      <!-- Main content area -->
      <div class="relative flex min-h-screen min-w-0 flex-1 flex-col">
        <header class="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
          <div class="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
            <div class="flex items-center gap-3">
              <button
                class="grid h-9 w-9 place-items-center rounded-md border border-slate-300 text-slate-600 hover:bg-slate-100 md:hidden"
                @click="mobileSidebarOpen = true"
              >
                <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
                </svg>
              </button>
              <div>
                <p class="text-sm font-semibold text-slate-900">{{ pageMeta.title }}</p>
                <p class="text-xs text-slate-500">{{ pageMeta.description }}</p>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <input
                type="search"
                placeholder="Search workspace"
                class="hidden h-9 w-52 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-700 outline-none ring-indigo-500 focus:ring sm:block"
              />
            </div>
          </div>
        </header>

        <main class="min-w-0 flex-1 p-4 sm:p-6">
          <slot />
        </main>
      </div>

      <!-- Mobile sidebar overlay -->
      <div v-if="mobileSidebarOpen" class="fixed inset-0 z-40 md:hidden">
        <div class="absolute inset-0 bg-slate-900/60" @click="mobileSidebarOpen = false" />
        <aside class="absolute left-0 top-0 flex h-full w-64 flex-col bg-slate-900">
          <div class="flex items-center justify-between px-4 py-5">
            <PayGlueLogo size="md" :dark="true" />
            <button class="rounded-md p-1.5 text-slate-400 hover:text-white" @click="mobileSidebarOpen = false">
              <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <nav class="flex-1 space-y-0.5 overflow-y-auto px-3 py-2">
            <template v-if="session.activeTenantSlug">

              <!-- Dashboard -->
              <RouterLink
                :to="`/t/${session.activeTenantSlug}/dashboard`"
                class="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors"
                :class="isActive(`/t/${session.activeTenantSlug}/dashboard`) ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                @click="mobileSidebarOpen = false"
              >
                <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
                </svg>
                Dashboard
              </RouterLink>

              <!-- Connection -->
              <div>
                <p class="mt-2 flex items-center gap-2 px-3 pb-1 text-[11px] font-semibold uppercase tracking-widest text-slate-600">
                  <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
                  </svg>
                  Connection
                </p>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/connection/ghost`"
                  class="block rounded-md px-3 py-1.5 text-sm transition-colors"
                  :class="isActive(`/t/${session.activeTenantSlug}/connection/ghost`) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                  @click="mobileSidebarOpen = false"
                >Ghost CMS</RouterLink>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/connection/polar`"
                  class="block rounded-md px-3 py-1.5 text-sm transition-colors"
                  :class="isActive(`/t/${session.activeTenantSlug}/connection/polar`) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                  @click="mobileSidebarOpen = false"
                >Polar</RouterLink>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/connection/paypal`"
                  class="block rounded-md px-3 py-1.5 text-sm transition-colors"
                  :class="isActive(`/t/${session.activeTenantSlug}/connection/paypal`) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                  @click="mobileSidebarOpen = false"
                >PayPal</RouterLink>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/connection/stripe`"
                  class="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors"
                  :class="isActive(`/t/${session.activeTenantSlug}/connection/stripe`) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                  @click="mobileSidebarOpen = false"
                >
                  Stripe
                  <span v-if="stripeConnected === true" class="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-emerald-900/50 text-emerald-400">Active</span>
                  <span v-else-if="stripeConnected === false" class="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-amber-900/50 text-amber-400">Disabled</span>
                </RouterLink>
              </div>

              <!-- Installation -->
              <div>
                <p class="mt-2 flex items-center gap-2 px-3 pb-1 text-[11px] font-semibold uppercase tracking-widest text-slate-600">
                  <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
                  </svg>
                  Installation
                </p>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/buttons`"
                  class="block rounded-md px-3 py-1.5 text-sm transition-colors"
                  :class="isActive(`/t/${session.activeTenantSlug}/buttons`) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                  @click="mobileSidebarOpen = false"
                >Buttons</RouterLink>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/paywall`"
                  class="block rounded-md px-3 py-1.5 text-sm transition-colors"
                  :class="isActive(`/t/${session.activeTenantSlug}/paywall`) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                  @click="mobileSidebarOpen = false"
                >Paywall</RouterLink>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/pricing`"
                  class="block rounded-md px-3 py-1.5 text-sm transition-colors"
                  :class="isActive(`/t/${session.activeTenantSlug}/pricing`) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                  @click="mobileSidebarOpen = false"
                >Pricing Table</RouterLink>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/installation`"
                  class="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors"
                  :class="isActive(`/t/${session.activeTenantSlug}/installation`) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                  @click="mobileSidebarOpen = false"
                >
                  Header script
                  <span
                    v-if="headerScriptInstalled"
                    class="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-emerald-900/50 text-emerald-400"
                  >Enabled</span>
                  <span
                    v-else
                    class="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-amber-900/50 text-amber-400"
                  >Disabled</span>
                </RouterLink>
              </div>

              <!-- Analytics -->
              <div>
                <p class="mt-2 flex items-center gap-2 px-3 pb-1 text-[11px] font-semibold uppercase tracking-widest text-slate-600">
                  <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M3 12h3l3-9 4 18 3-9h5" />
                  </svg>
                  Analytics
                </p>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/events`"
                  class="block rounded-md px-3 py-1.5 text-sm transition-colors"
                  :class="isActive(`/t/${session.activeTenantSlug}/events`) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                  @click="mobileSidebarOpen = false"
                >Webhook Events</RouterLink>
                <RouterLink
                  :to="`/t/${session.activeTenantSlug}/mappings`"
                  class="block rounded-md px-3 py-1.5 text-sm transition-colors"
                  :class="isActive(`/t/${session.activeTenantSlug}/mappings`) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                  @click="mobileSidebarOpen = false"
                >Product Mapping</RouterLink>
              </div>

            </template>

            <!-- Settings -->
            <div class="pt-2">
              <p class="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-widest text-slate-600">Settings</p>
              <RouterLink
                v-for="item in settingsItems"
                :key="`ms-${item.to}`"
                :to="item.to"
                class="block rounded-md px-3 py-2 text-sm transition-colors"
                :class="isActive(item.to) ? 'text-indigo-400 font-medium' : 'text-slate-400 hover:bg-slate-800 hover:text-white'"
                @click="mobileSidebarOpen = false"
              >{{ item.label }}</RouterLink>
            </div>
          </nav>
          <div class="border-t border-slate-800 px-3 py-3">
            <p class="truncate text-xs text-slate-500">{{ session.user?.email }}</p>
            <button class="mt-2 text-xs text-slate-500 hover:text-slate-200" @click="signOut">Sign out</button>
          </div>
        </aside>
      </div>

    </div>
  </div>
</template>

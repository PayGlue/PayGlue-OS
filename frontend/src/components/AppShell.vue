// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PayGlueLogo from './PayGlueLogo.vue'
import CommandPalette, { type PaletteItem } from './CommandPalette.vue'
import GracePeriodBanner from './GracePeriodBanner.vue'
import { useSessionStore } from '../stores/session'
import { checkHeaderScript, getGhostStripeStatus, getIntegrationConfig } from '../lib/api'
import { useHeaderScriptStatus } from '../composables/useHeaderScriptStatus'
import { useTheme } from '../composables/useTheme'

const { mode: themeMode, cycle: cycleTheme } = useTheme()
const themeLabel = computed(() =>
  themeMode.value === 'light' ? 'Light' : themeMode.value === 'dark' ? 'Dark' : 'System',
)

// "What's new" shown in the notifications popup. Add an entry whenever
// something worth surfacing ships; the popup links to the public changelog
// and roadmap. An unread dot shows on the bell while there are entries.
const newsItems = [
  { title: 'Get paid for your recommendations', body: 'Settings, Affiliate: 40% of every payment your referrals make. The calculator uses the real plan prices, so you can see what it is worth before you join.' },
  { title: 'Confirming no longer means logging out', body: 'Ownership transfers and account deletion now confirm in an overlay, with your authenticator app or a code by email.' },
  { title: 'Support got a rebuild', body: 'Pick a topic before you write, and find the docs, roadmap and status page right beside the form.' },
  { title: 'Your DPA is one click away', body: 'Settings, Documents: download the signed data processing agreement. Everyone who touches your data is now listed publicly too.' },
]
const hasNews = computed(() => newsItems.length > 0)

const session = useSessionStore()
const route = useRoute()
const router = useRouter()
const mobileSidebarOpen = ref(false)

const justLinkedProvider = ref<string | null>(null)
onMounted(() => {
  const flagged = sessionStorage.getItem('payglue:just-linked-provider')
  if (flagged) {
    justLinkedProvider.value = flagged
    sessionStorage.removeItem('payglue:just-linked-provider')
  }
})
const justLinkedProviderLabel = computed(() => {
  if (justLinkedProvider.value === 'google') return 'Google'
  if (justLinkedProvider.value === 'github') return 'GitHub'
  return justLinkedProvider.value
})
const orgDropdownOpen = ref(false)
const accountPopupOpen = ref(false)
const notificationsOpen = ref(false)
// PG: the docs button became a help menu. One icon in a cramped rail cannot
// carry three destinations, and support was the one people could not find at
// all -- it lived on a tenant-scoped page nothing linked to from the shell.
const helpOpen = ref(false)
const paletteOpen = ref(false)

const PROVIDERS = [
  { key: 'polar', name: 'Polar', status: 'available' as const },
  { key: 'paypal', name: 'PayPal', status: 'available' as const },
  { key: 'paddle', name: 'Paddle', status: 'available' as const },
  { key: 'gumroad', name: 'Gumroad', status: 'available' as const },
  { key: 'lemonsqueezy', name: 'Lemon Squeezy', status: 'available' as const },
  { key: 'kofi', name: 'Ko-fi', status: 'available' as const },
  { key: 'creem', name: 'Creem', status: 'available' as const },
  { key: 'patreon', name: 'Patreon', status: 'available' as const },
  { key: 'stripe', name: 'Stripe', status: 'deployment' as const },
]

const pageTitles: Record<string, { title: string; description: string }> = {
  dashboard: { title: 'Dashboard', description: 'Track tenant operations, replay health, and team activity.' },
  'connections-overview': { title: 'Connections', description: 'Connect Ghost and your payment providers.' },
  'connection-ghost': { title: 'Ghost CMS', description: 'Connect your Ghost instance and validate the Admin API.' },
  'connection-polar': { title: 'Polar', description: 'Connect Polar webhooks for automatic member sync.' },
  'connection-paypal': { title: 'PayPal', description: 'Connect PayPal webhooks for automatic member sync.' },
  'connection-gumroad': { title: 'Gumroad', description: 'Connect Gumroad webhooks for automatic member sync.' },
  'connection-paddle': { title: 'Paddle', description: 'Connect Paddle webhooks for automatic member sync.' },
  'connection-kofi': { title: 'Ko-fi', description: 'Connect Ko-fi webhooks for automatic member sync.' },
  'connection-creem': { title: 'Creem', description: 'Connect Creem webhooks for automatic member sync.' },
  'connection-patreon': { title: 'Patreon', description: 'Connect Patreon so active pledges grant Ghost access automatically.' },
  'connection-lemonsqueezy': { title: 'Lemon Squeezy', description: 'Connect Lemon Squeezy webhooks for automatic member sync.' },
  events: { title: 'Webhook Events', description: 'Inspect webhook pipelines and replay outcomes.' },
  mappings: { title: 'Product Mapping', description: 'Overview of all configured product-to-Ghost action mappings.' },
  billing: { title: 'Billing', description: 'Maintain billing profile and invoicing context.' },
  plans: { title: 'Plans & Pricing', description: 'Compare plans and upgrade or downgrade your subscription.' },
  team: { title: 'Team', description: 'Manage members, roles, and tenant permissions.' },
  organization: { title: 'Publication', description: 'Manage your publication identifier and danger zone.' },
  support: { title: 'Support', description: 'Get help from PayGlue support and manage support access.' },
  documents: { title: 'Documents', description: 'Download PayGlue legal and compliance documents.' },
  affiliate: { title: 'Affiliate', description: 'Earn 40% on everyone you bring to PayGlue.' },
  preferences: { title: 'Preferences', description: 'Account and workspace preferences.' },
  installation: { title: 'Installation', description: 'Copy embed snippets and validate hosted pricing render.' },
  pricing: { title: 'Pricing Tables', description: 'Build and embed pricing tables for your Ghost site.' },
}

// Icon paths reused across rail entries (kept as raw path data so both the
// desktop rail and mobile drawer render the exact same glyph).
const ICONS = {
  dashboard: 'M2.25 12l8.954-8.955a1.126 1.126 0 011.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25',
  connections: 'M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25',
  analytics: 'M3 12h3l3-9 4 18 3-9h5',
  installation: 'M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5',
  settings: 'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28z',
}

const { isInstalled: headerScriptInstalled, markInstalled, markNotInstalled } = useHeaderScriptStatus()
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
    // ignore -- badge stays null (no badge shown)
  }
}

// The installed/not-installed flag is cached in localStorage so it persists
// across page loads, but that cache is per-browser -- a fresh device or a
// freshly logged-in session with no cache falsely shows "not installed"
// until someone opens the Installation page and clicks the check button.
// Verify against the real backend on every login instead of trusting a
// possibly-empty local cache, same as the Stripe status above.
const loadHeaderScriptStatus = async () => {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  try {
    const result = await checkHeaderScript(slug, token)
    if (result.installed) markInstalled()
    else markNotInstalled()
  } catch {
    // ignore -- keep whatever the local cache last said
  }
}

// Light per-provider connection status for the small green/grey dots in the
// Connections sub-nav: connected vs not connected only (provider configs, no
// webhook-event data -- deliberately cheap).
const STATUS_PROVIDERS = ['polar', 'lemonsqueezy', 'paypal', 'gumroad', 'paddle', 'kofi', 'creem', 'patreon'] as const
const providerEnabled = ref<Record<string, boolean>>({})
const loadProviderStatuses = async () => {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  try {
    const keys = ['cms', ...STATUS_PROVIDERS] as const
    const results = await Promise.allSettled(keys.map((k) => getIntegrationConfig(slug, token, k)))
    const next: Record<string, boolean> = {}
    keys.forEach((k, i) => {
      const r = results[i]
      next[k] = r.status === 'fulfilled' && !!r.value?.enabled
    })
    providerEnabled.value = next
  } catch {
    // ignore -- dots just stay grey if statuses can't be loaded
  }
}

onMounted(loadStripeStatus)
onMounted(loadHeaderScriptStatus)
onMounted(loadProviderStatuses)
watch(() => session.activeTenantSlug, loadStripeStatus)
watch(() => session.activeTenantSlug, loadHeaderScriptStatus)
watch(() => session.activeTenantSlug, loadProviderStatuses)

const isActive = (to: string) => route.path === to

// ---- Sections: the top-level rail entries -------------------------------
const sections = computed(() => {
  const slug = session.activeTenantSlug
  if (!slug) return []
  return [
    { key: 'dashboard', label: 'Dashboard', icon: ICONS.dashboard, to: `/t/${slug}/dashboard` },
    { key: 'connections', label: 'Connections', icon: ICONS.connections, to: `/t/${slug}/connections` },
    { key: 'analytics', label: 'Analytics', icon: ICONS.analytics, to: `/t/${slug}/events` },
    { key: 'installation', label: 'Features', icon: ICONS.installation, to: `/t/${slug}/buttons` },
    { key: 'settings', label: 'Settings', icon: ICONS.settings, to: `/t/${slug}/team` },
  ]
})

// Sections whose sub-navigation now lives inline in the rail (expand/collapse)
// instead of the old tab row under the header.
const GROUPS_WITH_SUBNAV = new Set(['connections', 'analytics', 'installation', 'settings'])

const activeSectionKey = computed(() => {
  const p = route.path
  if (p.includes('/connection')) return 'connections'
  if (p.includes('/events') || p.includes('/mappings')) return 'analytics'
  if (p.includes('/installation') || p.includes('/buttons') || p.includes('/paywall') || p.includes('/pricing')) return 'installation'
  if (p.includes('/team') || p.includes('/billing') || p.includes('/plans') || p.includes('/preferences') || p.includes('/organization') || p.includes('/support') || p.includes('/documents')) return 'settings'
  return 'dashboard'
})

const activeSectionLabel = computed(() =>
  sections.value.find(s => s.key === activeSectionKey.value)?.label ?? 'Dashboard',
)

// ---- Tabs: the sub-navigation for whichever section is active -----------
type TabItem = { label: string; to: string; badge?: 'on' | 'off' | 'soon' | 'planned' | null; dot?: 'good' | 'muted' | null; disabled?: boolean }

const connectionTabs = computed<TabItem[]>(() => {
  const slug = session.activeTenantSlug
  if (!slug) return []
  const tabs: TabItem[] = [
    { label: 'Overview', to: `/t/${slug}/connections` },
    { label: 'Ghost CMS', to: `/t/${slug}/connection/ghost`, dot: providerEnabled.value['cms'] ? 'good' : 'muted' },
  ]
  for (const p of PROVIDERS) {
    if (p.status === 'available' || p.key === 'stripe') {
      let badge: TabItem['badge'] = null
      if (p.key === 'stripe') badge = stripeConnected.value === true ? 'on' : stripeConnected.value === false ? 'off' : null
      // Green/grey dot: connected vs not (Stripe keeps its own on/off badge).
      const dot: TabItem['dot'] = p.key === 'stripe' ? null : providerEnabled.value[p.key] ? 'good' : 'muted'
      tabs.push({ label: p.name, to: `/t/${slug}/connection/${p.key}`, badge, dot })
    } else {
      tabs.push({ label: p.name, to: '', disabled: true, badge: p.status === 'deployment' ? 'soon' : 'planned' })
    }
  }
  return tabs
})

const installationTabs = computed<TabItem[]>(() => {
  const slug = session.activeTenantSlug
  if (!slug) return []
  return [
    { label: 'Buttons', to: `/t/${slug}/buttons` },
    { label: 'Paywall', to: `/t/${slug}/paywall` },
    { label: 'Pricing Table', to: `/t/${slug}/pricing` },
    { label: 'Header Script', to: `/t/${slug}/installation`, badge: headerScriptInstalled.value ? 'on' : 'off' },
  ]
})

const analyticsTabs = computed<TabItem[]>(() => {
  const slug = session.activeTenantSlug
  if (!slug) return []
  return [
    { label: 'Webhook Events', to: `/t/${slug}/events` },
    { label: 'Product Mapping', to: `/t/${slug}/mappings` },
  ]
})

const settingsTabs = computed<TabItem[]>(() => {
  const slug = session.activeTenantSlug
  if (!slug) return []
  return [
    { label: 'Team', to: `/t/${slug}/team` },
    { label: 'Billing', to: `/t/${slug}/billing` },
    { label: 'Plans', to: `/t/${slug}/plans` },
    { label: 'Affiliate', to: `/t/${slug}/affiliate` },
    { label: 'Preferences', to: `/t/${slug}/preferences` },
    { label: 'Publication', to: `/t/${slug}/organization` },
    { label: 'Support', to: `/t/${slug}/support` },
    // Documents is the DPA/legal-download tab -- PayGlue-company paperwork,
    // not product. The OSS router deliberately has no such route, so gating
    // on hasRoute makes the tab disappear there without a fork of this file.
    // Same graceful-degradation pattern PreferencesView uses for 'goodbye'.
    ...(router.hasRoute('documents') ? [{ label: 'Documents', to: `/t/${slug}/documents` }] : []),
  ]
})

const tabsForSection = (key: string): TabItem[] => {
  switch (key) {
    case 'connections': return connectionTabs.value
    case 'installation': return installationTabs.value
    case 'analytics': return analyticsTabs.value
    case 'settings': return settingsTabs.value
    default: return []
  }
}

// The sub-item matching the current route, shown as the second breadcrumb
// segment (e.g. "Connections / Creem") -- null when the section has no
// sub-nav (Dashboard) or no sub-item is active yet.
const activeSubLabel = computed(() => {
  const match = tabsForSection(activeSectionKey.value).find(t => !t.disabled && isActive(t.to))
  return match ? match.label : null
})

// ---- Rail groups: which sections are expanded ----------------------------
// Multiple groups can be open at once (matches the mobile drawer's previous
// behaviour and the Creem-style rail this was modeled on) -- opening the
// group for the current route doesn't force-close any other one the user
// already expanded.
const expandedGroups = ref<Record<string, boolean>>({})
watch(activeSectionKey, (key) => { expandedGroups.value[key] = true }, { immediate: true })
const toggleGroup = (key: string) => { expandedGroups.value[key] = !expandedGroups.value[key] }
const goToSection = (key: string) => {
  expandedGroups.value[key] = true
  const s = sections.value.find(sec => sec.key === key)
  if (s) router.push(s.to)
}

// ---- Command palette (⌘K / Ctrl+K) ---------------------------------------
const allNavItems = computed<PaletteItem[]>(() => {
  const items: PaletteItem[] = []
  for (const s of sections.value) {
    if (!GROUPS_WITH_SUBNAV.has(s.key)) {
      items.push({ label: s.label, sectionLabel: 'Overview', to: s.to })
      continue
    }
    for (const t of tabsForSection(s.key)) {
      if (t.disabled) continue
      items.push({ label: t.label, sectionLabel: s.label, to: t.to })
    }
  }
  return items
})

const onGlobalKeydown = (e: KeyboardEvent) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    mobileSidebarOpen.value = false
    paletteOpen.value = true
  }
}
onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => window.removeEventListener('keydown', onGlobalKeydown))

const pageMeta = computed(() => {
  const key = String(route.name ?? '')
  return pageTitles[key] ?? { title: 'Control panel', description: 'Manage tenant configuration and operations.' }
})

const switchOrg = (tenantSlug: string) => {
  orgDropdownOpen.value = false
  if (tenantSlug === session.activeTenantSlug) return
  session.setActiveTenant(tenantSlug)
  mobileSidebarOpen.value = false
  router.push(`/t/${tenantSlug}/dashboard`)
}

// Tenant slugs are stored lowercase (they double as URL segments), but a
// slug is not the same thing as a display name -- render it title-cased
// so "payglue" / "acme-media" read as "Payglue" / "Acme Media".
const displayTenant = (slug: string | null | undefined) => {
  if (!slug) return ''
  return slug
    .split(/[-_]/)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

const signOut = async () => {
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
  <div class="pg-shell min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
    <div class="flex min-h-screen">

      <!-- Desktop rail -->
      <aside class="hidden w-64 shrink-0 flex-col border-r border-slate-800/60 bg-slate-900 py-5 md:flex">
        <div class="mb-5 flex items-center gap-2 px-4" title="PayGlue">
          <div class="h-7 w-7 shrink-0">
            <svg viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg" class="h-full w-full">
              <rect x="0" y="0" width="256" height="256" rx="58" fill="#5B5BD6"/>
              <circle cx="94" cy="128" r="62" fill="none" stroke="white" stroke-width="22" opacity="0.35"/>
              <circle cx="162" cy="128" r="62" fill="none" stroke="white" stroke-width="22"/>
              <rect x="114" y="66" width="28" height="124" fill="#5B5BD6"/>
              <rect x="119" y="102" width="18" height="52" rx="9" fill="white"/>
            </svg>
          </div>
          <span class="text-sm font-bold tracking-tight text-white">PayGlue</span>
        </div>

        <!-- Workspace switcher -->
        <div v-if="session.memberships.length" class="relative px-3 pb-4">
          <div v-if="orgDropdownOpen" class="fixed inset-0 z-10" @click="orgDropdownOpen = false" />
          <button
            class="relative z-20 flex w-full items-center gap-2.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2.5 text-left transition-colors hover:border-slate-600"
            @click="orgDropdownOpen = !orgDropdownOpen"
          >
            <div class="grid h-6 w-6 shrink-0 place-items-center rounded bg-indigo-900 text-[10px] font-semibold text-indigo-300">
              {{ session.activeTenantSlug?.[0]?.toUpperCase() ?? '?' }}
            </div>
            <span class="min-w-0 flex-1 truncate text-[13px] font-medium text-slate-100">{{ displayTenant(session.activeTenantSlug) }}</span>
            <span v-if="session.activeMembership?.status === 'paused'" class="shrink-0 rounded-full bg-amber-900/50 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">Paused</span>
            <svg class="h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform" :class="orgDropdownOpen ? 'rotate-180' : ''" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
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
              <span class="flex-1 truncate text-xs text-slate-300">{{ displayTenant(m.tenant_slug) }}</span>
              <span v-if="m.status === 'paused'" class="shrink-0 rounded-full bg-amber-900/50 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">Paused</span>
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
                Add publication
              </RouterLink>
            </div>
          </div>
        </div>

        <!-- Nav: flat links for Dashboard, expandable groups for everything with sub-pages -->
        <nav class="flex flex-1 flex-col gap-1 overflow-y-auto px-3">
          <template v-for="s in sections" :key="s.key">
            <RouterLink
              v-if="!GROUPS_WITH_SUBNAV.has(s.key)"
              :to="s.to"
              class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13.5px] font-medium transition-colors"
              :class="activeSectionKey === s.key ? 'bg-indigo-600 text-white' : 'text-slate-100 hover:bg-slate-800'"
            >
              <svg class="h-[18px] w-[18px] shrink-0" :class="activeSectionKey === s.key ? 'opacity-100' : 'opacity-70'" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" :d="s.icon" />
              </svg>
              {{ s.label }}
            </RouterLink>

            <div v-else>
              <button
                type="button"
                class="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-[13.5px] font-medium transition-colors"
                :class="activeSectionKey === s.key ? 'text-white' : 'text-slate-100 hover:bg-slate-800'"
                @click="toggleGroup(s.key)"
              >
                <span class="flex items-center gap-3">
                  <svg class="h-[18px] w-[18px] shrink-0" :class="activeSectionKey === s.key ? 'opacity-100' : 'opacity-70'" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" :d="s.icon" />
                  </svg>
                  {{ s.label }}
                </span>
                <span
                  class="grid h-5 w-5 shrink-0 place-items-center rounded-md border transition-colors"
                  :class="expandedGroups[s.key] ? 'border-slate-600 text-slate-200' : 'border-slate-700 text-slate-500'"
                >
                  <svg v-if="!expandedGroups[s.key]" class="h-2.5 w-2.5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" d="M12 5v14M5 12h14" /></svg>
                  <svg v-else class="h-2.5 w-2.5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" d="M5 12h14" /></svg>
                </span>
              </button>

              <div v-if="expandedGroups[s.key]" class="ml-[25px] mt-1 flex flex-col gap-0.5 border-l border-slate-800 py-0.5 pl-3.5">
                <template v-for="tab in tabsForSection(s.key)" :key="tab.label">
                  <RouterLink
                    v-if="!tab.disabled"
                    :to="tab.to"
                    class="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] transition-colors"
                    :class="isActive(tab.to) ? 'bg-slate-800 font-medium text-white' : 'text-slate-400 hover:text-slate-100'"
                  >
                    <span v-if="tab.dot" class="h-1.5 w-1.5 shrink-0 rounded-full" :class="tab.dot === 'good' ? 'bg-emerald-500' : 'bg-slate-600'" :title="tab.dot === 'good' ? 'Connected' : 'Not connected'"></span>
                    {{ tab.label }}
                    <span v-if="tab.badge === 'on'" class="ml-auto rounded-full bg-emerald-900/50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">Active</span>
                    <span v-else-if="tab.badge === 'off'" class="ml-auto rounded-full bg-amber-900/50 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">Disabled</span>
                  </RouterLink>
                  <div v-else class="flex items-center gap-2 px-2.5 py-1.5 text-[13px]">
                    <span class="text-slate-600">{{ tab.label }}</span>
                    <span class="ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-medium" :class="tab.badge === 'soon' ? 'bg-sky-900/40 text-sky-400' : 'bg-slate-800 text-slate-500'">
                      {{ tab.badge === 'soon' ? 'Soon' : 'Planned' }}
                    </span>
                  </div>
                </template>
              </div>
            </div>
          </template>
        </nav>

        <!-- Footer: avatar, notifications, docs, search -->
        <div class="mt-2 flex items-center gap-1.5 border-t border-slate-800 px-3 pt-3.5">
          <div class="relative">
            <div v-if="accountPopupOpen" class="fixed inset-0 z-10" @click="accountPopupOpen = false" />
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
                class="absolute bottom-full left-0 z-20 mb-2 w-60 overflow-hidden rounded-xl border border-slate-700 bg-slate-800 shadow-2xl"
              >
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
                    Publication
                  </RouterLink>
                  <RouterLink
                    to="/tenant/create"
                    class="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-slate-300 transition-colors hover:bg-slate-700 hover:text-white"
                    @click="accountPopupOpen = false"
                  >
                    <svg class="h-4 w-4 shrink-0 text-slate-500" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                    </svg>
                    New Publication
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

            <button
              class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-indigo-600/20 text-xs font-semibold text-indigo-300 transition-colors hover:bg-indigo-600/30"
              :title="accountDisplayName"
              @click="accountPopupOpen = !accountPopupOpen"
            >
              {{ accountDisplayName.charAt(0).toUpperCase() }}
            </button>
          </div>

          <!-- Search (Lupe) sits before the bell -->
          <button
            type="button"
            class="ml-auto grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-700 text-slate-400 transition-colors hover:border-slate-600 hover:text-slate-100"
            title="Search (⌘K)"
            @click="paletteOpen = true"
          >
            <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <circle cx="11" cy="11" r="7" /><path stroke-linecap="round" d="M21 21l-4.3-4.3" />
            </svg>
          </button>

          <div class="relative">
            <div v-if="notificationsOpen" class="fixed inset-0 z-10" @click="notificationsOpen = false" />
            <div
              v-if="notificationsOpen"
              class="absolute bottom-full left-0 z-20 mb-2 w-64 overflow-hidden rounded-xl border border-slate-700 bg-slate-800 shadow-2xl"
            >
              <div class="border-b border-slate-700 px-4 py-2.5">
                <p class="text-xs font-semibold text-slate-200">What's new</p>
              </div>
              <div v-for="(n, i) in newsItems" :key="i" class="px-4 py-3">
                <p class="text-xs font-semibold text-slate-100">{{ n.title }}</p>
                <p class="mt-0.5 text-xs leading-relaxed text-slate-400">{{ n.body }}</p>
              </div>
              <p v-if="!newsItems.length" class="px-4 py-3 text-xs text-slate-500">You're all caught up.</p>
              <div class="flex items-center gap-4 border-t border-slate-700 px-4 py-2.5">
                <RouterLink to="/changelog" class="text-xs font-semibold text-indigo-400 hover:text-indigo-300" @click="notificationsOpen = false">Changelog →</RouterLink>
                <RouterLink to="/roadmap" class="text-xs font-semibold text-indigo-400 hover:text-indigo-300" @click="notificationsOpen = false">Roadmap →</RouterLink>
              </div>
            </div>
            <button
              type="button"
              class="relative grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-700 text-slate-400 transition-colors hover:border-slate-600 hover:text-slate-100"
              title="Notifications"
              @click="notificationsOpen = !notificationsOpen"
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" />
              </svg>
              <span v-if="hasNews" class="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-indigo-400 ring-2 ring-slate-900"></span>
            </button>
          </div>

          <div class="relative">
            <div v-if="helpOpen" class="fixed inset-0 z-10" @click="helpOpen = false" />
            <div
              v-if="helpOpen"
              class="absolute bottom-full left-0 z-20 mb-2 w-56 overflow-hidden rounded-xl border border-slate-700 bg-slate-800 shadow-2xl"
            >
              <RouterLink
                v-if="session.activeTenantSlug"
                :to="`/t/${session.activeTenantSlug}/support`"
                class="flex items-center gap-3 px-4 py-2.5 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700"
                @click="helpOpen = false"
              >
                <svg class="h-4 w-4 shrink-0 text-slate-400" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                Support
              </RouterLink>
              <a
                href="https://status.payglue.io"
                target="_blank"
                rel="noopener"
                class="flex items-center gap-3 px-4 py-2.5 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700"
                @click="helpOpen = false"
              >
                <svg class="h-4 w-4 shrink-0 text-slate-400" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 12h4l3 8 4-16 3 8h4" />
                </svg>
                System Status
              </a>
              <a
                href="https://docs.payglue.io"
                target="_blank"
                rel="noopener"
                class="flex items-center gap-3 px-4 py-2.5 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700"
                @click="helpOpen = false"
              >
                <svg class="h-4 w-4 shrink-0 text-slate-400" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                </svg>
                Documentation
              </a>
            </div>
            <button
              type="button"
              class="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-700 text-slate-400 transition-colors hover:border-slate-600 hover:text-slate-100"
              title="Help"
              aria-label="Help"
              @click="helpOpen = !helpOpen"
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="9" />
                <path stroke-linecap="round" stroke-linejoin="round" d="M9.5 9.5a2.5 2.5 0 114 2c-.8.6-1.5 1.1-1.5 2" />
                <circle cx="12" cy="17" r="0.5" fill="currentColor" />
              </svg>
            </button>
          </div>

          <!-- Theme toggle: cycles Light → Dark → System -->
          <button
            type="button"
            class="group grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-700 text-slate-400 transition-colors hover:border-slate-600 hover:text-slate-100"
            :title="`Theme: ${themeLabel} (click to change)`"
            :aria-label="`Theme: ${themeLabel}`"
            @click="cycleTheme"
          >
            <Transition
              enter-active-class="transition duration-300 ease-out"
              enter-from-class="-rotate-90 scale-0 opacity-0"
              leave-active-class="transition duration-200 ease-in absolute"
              leave-to-class="rotate-90 scale-0 opacity-0"
              mode="out-in"
            >
              <!-- Light: sun -->
              <svg v-if="themeMode === 'light'" key="light" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="4" /><path stroke-linecap="round" d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
              </svg>
              <!-- Dark: moon -->
              <svg v-else-if="themeMode === 'dark'" key="dark" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
              </svg>
              <!-- System: monitor -->
              <svg v-else key="system" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <rect x="3" y="4" width="18" height="12" rx="2" /><path stroke-linecap="round" d="M8 20h8m-4-4v4" />
              </svg>
            </Transition>
          </button>
        </div>
      </aside>

      <!-- Main content area -->
      <div class="relative flex min-h-screen min-w-0 flex-1 flex-col">
        <header class="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
          <!-- Mobile header: hamburger + plain title -->
          <div class="flex items-center justify-between gap-4 px-4 py-3 md:hidden">
            <div class="flex items-center gap-3">
              <button
                class="grid h-9 w-9 place-items-center rounded-md border border-slate-300 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                @click="mobileSidebarOpen = true"
              >
                <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
                </svg>
              </button>
              <div>
                <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ pageMeta.title }}</p>
                <p class="text-xs text-slate-500 dark:text-slate-400">{{ pageMeta.description }}</p>
              </div>
            </div>
            <button
              type="button"
              class="grid h-9 w-9 place-items-center rounded-md border border-slate-300 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              title="Search"
              @click="paletteOpen = true"
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <circle cx="11" cy="11" r="7" /><path stroke-linecap="round" d="M21 21l-4.3-4.3" />
              </svg>
            </button>
          </div>

          <!-- Desktop header: Finder-style breadcrumb, both segments clickable -->
          <div class="hidden items-center justify-between gap-4 px-5 py-2.5 md:flex">
            <div class="flex min-w-0 items-center gap-1.5 text-sm">
              <button
                type="button"
                class="truncate rounded-md px-1.5 py-1 font-semibold text-slate-800 transition-colors hover:bg-slate-100 dark:text-slate-100 dark:hover:bg-slate-800"
                @click="goToSection(activeSectionKey)"
              >
                {{ activeSectionLabel }}
              </button>
              <template v-if="activeSubLabel">
                <span class="text-slate-300 dark:text-slate-600">/</span>
                <span class="truncate rounded-md px-1.5 py-1 font-medium text-slate-500 dark:text-slate-400">{{ activeSubLabel }}</span>
              </template>
            </div>

            <div class="flex items-center gap-1">
              <a
                href="mailto:team@payglue.io"
                title="Support"
                class="grid h-8 w-8 place-items-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
              >
                <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
                </svg>
              </a>
            </div>
          </div>
        </header>

        <main class="min-w-0 flex-1 overflow-x-clip p-4 sm:p-6">
          <GracePeriodBanner />
          <div v-if="justLinkedProvider" class="mb-4 flex items-start justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            <span>Your {{ justLinkedProviderLabel }} account has been linked to your existing PayGlue account.</span>
            <button type="button" class="shrink-0 text-emerald-600 hover:text-emerald-900" @click="justLinkedProvider = null">
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <slot />
        </main>
      </div>

      <!-- Mobile sidebar overlay -->
      <div v-if="mobileSidebarOpen" class="fixed inset-0 z-40 md:hidden">
        <div class="absolute inset-0 bg-slate-900/60" @click="mobileSidebarOpen = false" />
        <aside class="absolute left-0 top-0 flex h-full w-72 flex-col bg-slate-900">
          <div class="flex items-center justify-between px-4 py-5">
            <PayGlueLogo size="md" :dark="true" />
            <button class="rounded-md p-1.5 text-slate-400 hover:text-white" @click="mobileSidebarOpen = false">
              <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Workspace switcher -->
          <div v-if="session.memberships.length" class="px-3 pb-3">
            <button
              class="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2.5 text-left transition-colors hover:border-slate-600"
              @click="orgDropdownOpen = !orgDropdownOpen"
            >
              <div class="flex items-center gap-2.5">
                <div class="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-indigo-900 text-xs font-semibold text-indigo-300">
                  {{ session.activeTenantSlug?.[0]?.toUpperCase() ?? '?' }}
                </div>
                <div class="min-w-0 flex-1">
                  <p class="truncate text-[13px] font-medium text-slate-100">{{ displayTenant(session.activeTenantSlug) }}</p>
                </div>
                <span v-if="session.activeMembership?.status === 'paused'" class="shrink-0 rounded-full bg-amber-900/50 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">Paused</span>
                <svg class="h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform" :class="orgDropdownOpen ? 'rotate-180' : ''" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </div>
            </button>
            <div v-if="orgDropdownOpen" class="mt-1 overflow-hidden rounded-lg border border-slate-700 bg-slate-800">
              <div
                v-for="m in session.memberships"
                :key="m.tenant_slug"
                class="flex cursor-pointer items-center gap-2 px-3 py-2 transition-colors hover:bg-slate-700"
                @click="switchOrg(m.tenant_slug)"
              >
                <div class="grid h-6 w-6 shrink-0 place-items-center rounded bg-indigo-900 text-[10px] font-semibold text-indigo-300">
                  {{ m.tenant_slug[0]?.toUpperCase() }}
                </div>
                <span class="flex-1 truncate text-xs text-slate-300">{{ displayTenant(m.tenant_slug) }}</span>
                <span v-if="m.status === 'paused'" class="shrink-0 rounded-full bg-amber-900/50 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">Paused</span>
                <svg v-if="m.tenant_slug === session.activeTenantSlug" class="h-3.5 w-3.5 text-indigo-400" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
              </div>
              <RouterLink
                to="/tenant/create"
                class="flex items-center gap-2 border-t border-slate-700 px-3 py-2 text-xs text-slate-500 transition-colors hover:bg-slate-700 hover:text-slate-200"
                @click="orgDropdownOpen = false; mobileSidebarOpen = false"
              >
                <svg class="h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
                Add publication
              </RouterLink>
            </div>
          </div>

          <!-- Same expand/collapse pattern as desktop: multiple groups can stay open -->
          <nav class="flex-1 space-y-1 overflow-y-auto px-3 py-2">
            <template v-if="session.activeTenantSlug">
              <template v-for="s in sections" :key="s.key">
                <RouterLink
                  v-if="!GROUPS_WITH_SUBNAV.has(s.key)"
                  :to="s.to"
                  class="flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors"
                  :class="activeSectionKey === s.key ? 'bg-indigo-600 text-white' : 'text-slate-100 hover:bg-slate-800'"
                  @click="mobileSidebarOpen = false"
                >
                  <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" :d="s.icon" />
                  </svg>
                  {{ s.label }}
                </RouterLink>

                <div v-else>
                  <button
                    type="button"
                    class="flex w-full items-center justify-between gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors"
                    :class="activeSectionKey === s.key ? 'text-white' : 'text-slate-100 hover:bg-slate-800'"
                    @click="toggleGroup(s.key)"
                  >
                    <span class="flex items-center gap-3">
                      <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" :d="s.icon" />
                      </svg>
                      {{ s.label }}
                    </span>
                    <span
                      class="grid h-5 w-5 shrink-0 place-items-center rounded-md border transition-colors"
                      :class="expandedGroups[s.key] ? 'border-slate-600 text-slate-200' : 'border-slate-700 text-slate-500'"
                    >
                      <svg v-if="!expandedGroups[s.key]" class="h-2.5 w-2.5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" d="M12 5v14M5 12h14" /></svg>
                      <svg v-else class="h-2.5 w-2.5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" d="M5 12h14" /></svg>
                    </span>
                  </button>

                  <div v-if="expandedGroups[s.key]" class="ml-[23px] mt-0.5 flex flex-col gap-0.5 border-l border-slate-800 py-0.5 pl-3.5">
                    <template v-for="tab in tabsForSection(s.key)" :key="tab.label">
                      <RouterLink
                        v-if="!tab.disabled"
                        :to="tab.to"
                        class="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors"
                        :class="isActive(tab.to) ? 'bg-slate-800 font-medium text-white' : 'text-slate-400 hover:text-slate-100'"
                        @click="mobileSidebarOpen = false"
                      >
                        <span v-if="tab.dot" class="h-1.5 w-1.5 shrink-0 rounded-full" :class="tab.dot === 'good' ? 'bg-emerald-500' : 'bg-slate-600'"></span>
                        {{ tab.label }}
                        <span v-if="tab.badge === 'on'" class="ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-emerald-900/50 text-emerald-400">Active</span>
                        <span v-else-if="tab.badge === 'off'" class="ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-amber-900/50 text-amber-400">Disabled</span>
                      </RouterLink>
                      <div v-else class="flex items-center gap-2 px-2.5 py-1.5">
                        <span class="text-sm text-slate-600">{{ tab.label }}</span>
                        <span class="ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-medium" :class="tab.badge === 'soon' ? 'bg-sky-900/40 text-sky-400' : 'bg-slate-800 text-slate-500'">
                          {{ tab.badge === 'soon' ? 'Soon' : 'Planned' }}
                        </span>
                      </div>
                    </template>
                  </div>
                </div>
              </template>
            </template>
          </nav>

          <!-- Account popup opens UPWARD (above the footer row) so it is never pushed off-screen -->
          <div v-if="accountPopupOpen" class="border-t border-slate-800 px-4 py-3">
            <p class="truncate text-xs font-medium text-slate-200">{{ accountDisplayName }}</p>
            <p class="truncate text-xs text-slate-500">{{ session.user?.email }}</p>
            <button class="mt-2 text-xs text-rose-400 hover:text-rose-300" @click="signOut">Sign out</button>
          </div>

          <!-- What's new opens UPWARD above the footer row -->
          <div v-if="helpOpen" class="border-t border-slate-800 px-4 py-2">
            <RouterLink
              v-if="session.activeTenantSlug"
              :to="`/t/${session.activeTenantSlug}/support`"
              class="flex items-center gap-3 py-2 text-xs font-medium text-slate-200"
              @click="helpOpen = false; mobileSidebarOpen = false"
            >
              <svg class="h-4 w-4 shrink-0 text-slate-400" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              Support
            </RouterLink>
            <a
              href="https://status.payglue.io"
              target="_blank"
              rel="noopener"
              class="flex items-center gap-3 py-2 text-xs font-medium text-slate-200"
              @click="helpOpen = false"
            >
              <svg class="h-4 w-4 shrink-0 text-slate-400" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 12h4l3 8 4-16 3 8h4" />
              </svg>
              System Status
            </a>
            <a
              href="https://docs.payglue.io"
              target="_blank"
              rel="noopener"
              class="flex items-center gap-3 py-2 text-xs font-medium text-slate-200"
              @click="helpOpen = false"
            >
              <svg class="h-4 w-4 shrink-0 text-slate-400" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
              </svg>
              Documentation
            </a>
          </div>
          <div v-if="notificationsOpen" class="border-t border-slate-800 px-4 py-3">
            <p class="text-xs font-semibold text-slate-200">What's new</p>
            <div v-for="(n, i) in newsItems" :key="i" class="mt-2">
              <p class="text-xs font-semibold text-slate-100">{{ n.title }}</p>
              <p class="mt-0.5 text-xs leading-relaxed text-slate-400">{{ n.body }}</p>
            </div>
            <p v-if="!newsItems.length" class="mt-1 text-xs text-slate-500">You're all caught up.</p>
            <div class="mt-2.5 flex items-center gap-4">
              <RouterLink to="/changelog" class="text-xs font-semibold text-indigo-400" @click="notificationsOpen = false; mobileSidebarOpen = false">Changelog →</RouterLink>
              <RouterLink to="/roadmap" class="text-xs font-semibold text-indigo-400" @click="notificationsOpen = false; mobileSidebarOpen = false">Roadmap →</RouterLink>
            </div>
          </div>

          <!-- Same footer icon row as desktop (search before the bell) -->
          <div class="flex items-center gap-1.5 border-t border-slate-800 px-3 py-3.5">
            <button
              type="button"
              class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-indigo-600/20 text-xs font-semibold text-indigo-300"
              :title="accountDisplayName"
              @click="accountPopupOpen = !accountPopupOpen"
            >
              {{ accountDisplayName.charAt(0).toUpperCase() }}
            </button>
            <button
              type="button"
              class="ml-auto grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-700 text-slate-400"
              title="Search"
              @click="paletteOpen = true"
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <circle cx="11" cy="11" r="7" /><path stroke-linecap="round" d="M21 21l-4.3-4.3" />
              </svg>
            </button>
            <button
              type="button"
              class="relative grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-700 text-slate-400"
              title="Notifications"
              @click="notificationsOpen = !notificationsOpen"
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" />
              </svg>
              <span v-if="hasNews" class="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-indigo-400 ring-2 ring-slate-900"></span>
            </button>
            <button
              type="button"
              class="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-slate-700 text-slate-400"
              title="Help"
              aria-label="Help"
              @click="helpOpen = !helpOpen"
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="9" />
                <path stroke-linecap="round" stroke-linejoin="round" d="M9.5 9.5a2.5 2.5 0 114 2c-.8.6-1.5 1.1-1.5 2" />
                <circle cx="12" cy="17" r="0.5" fill="currentColor" />
              </svg>
            </button>

            <!-- Theme toggle: cycles Light → Dark → System (same as desktop rail) -->
            <button
              type="button"
              class="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-indigo-500/40 text-indigo-300"
              :title="`Theme: ${themeLabel} (click to change)`"
              :aria-label="`Theme: ${themeLabel}`"
              @click="cycleTheme"
            >
              <svg v-if="themeMode === 'light'" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="4" /><path stroke-linecap="round" d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
              </svg>
              <svg v-else-if="themeMode === 'dark'" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
              </svg>
              <svg v-else class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
                <rect x="3" y="4" width="18" height="12" rx="2" /><path stroke-linecap="round" d="M8 20h8m-4-4v4" />
              </svg>
            </button>
          </div>

        </aside>
      </div>

    </div>

    <CommandPalette v-model:open="paletteOpen" :items="allNavItems" />
  </div>
</template>

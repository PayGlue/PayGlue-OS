// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

const kpiCards = [
  { label: 'Failed events', value: '8', hint: 'Webhook deliveries requiring action' },
  { label: 'Replay queue', value: '5', hint: 'Eligible for replay by admin/owner' },
  { label: 'Active mappings', value: '42', hint: 'Product-to-access rules in production' },
  { label: 'Team members', value: '7', hint: 'Workspace users with active roles' },
]

const events = [
  { id: 1421, provider: 'stripe', status: 'failed', attempts: 3, createdAt: '2026-03-19 10:34' },
  { id: 1419, provider: 'ghost', status: 'processed', attempts: 1, createdAt: '2026-03-19 10:31' },
  { id: 1416, provider: 'polar', status: 'dead_letter', attempts: 5, createdAt: '2026-03-19 10:20' },
  { id: 1413, provider: 'stripe', status: 'processed', attempts: 1, createdAt: '2026-03-19 10:11' },
]

const audits = [
  { type: 'mapping.created', target: 'product_map', id: 'pm_481', at: '2026-03-19 09:58' },
  { type: 'integration.updated', target: 'payment', id: 'stripe', at: '2026-03-19 09:40' },
  { type: 'billing.updated', target: 'billing_profile', id: 'tenant-default', at: '2026-03-19 09:12' },
]

const previewNavGroups = [
  {
    title: 'General',
    links: [
      { label: 'Dashboard', href: '#dashboard' },
      { label: 'Connect Ghost', href: '#connect-ghost' },
      { label: 'Events', href: '#events' },
    ],
  },
  {
    title: 'Operations',
    links: [
      { label: 'Mappings', href: '#dashboard' },
      { label: 'Integrations', href: '#dashboard' },
      { label: 'Billing', href: '#dashboard' },
    ],
  },
  {
    title: 'Workspace',
    links: [
      { label: 'Team', href: '#dashboard' },
      { label: 'Installation', href: '#installation' },
      { label: 'Pricing Table', href: '#pricing-table' },
    ],
  },
]

const connectForm = reactive({
  contentApiKey: '',
  adminApiKey: '',
  apiUrl: 'http://ghost:2368/ghost/api/admin',
})

const connectSuccess = ref<string | null>(null)
const connectError = ref<string | null>(null)

const savePreviewConnect = () => {
  connectSuccess.value = null
  connectError.value = null
  if (!connectForm.contentApiKey.trim() || !connectForm.adminApiKey.trim() || !connectForm.apiUrl.trim()) {
    connectError.value = 'Content API key, Admin API key, and API URL are required.'
    return
  }
  localStorage.setItem(
    'payglue:preview-connect',
    JSON.stringify({
      contentApiKey: connectForm.contentApiKey.trim(),
      adminApiKey: connectForm.adminApiKey.trim(),
      apiUrl: connectForm.apiUrl.trim(),
    }),
  )
  connectSuccess.value = 'Saved in preview mode (browser storage only).'
}

const runPreviewHealth = () => {
  connectSuccess.value = null
  connectError.value = null
  if (!connectForm.contentApiKey.trim() || !connectForm.adminApiKey.trim() || !connectForm.apiUrl.trim()) {
    connectError.value = 'Fill all fields before running health check.'
    return
  }
  connectSuccess.value = 'Preview mode: use /t/:tenant/connect for real backend health checks.'
}

const pricingBuilder = reactive({
  title: 'PayGlue Pricing',
  subtitle: 'Transparent pricing for Ghost + Polar rollout.',
  handle: 'tenant-dev-pricing',
})

const pricingTableSnippet = computed(() => {
  const payload = JSON.stringify(
    {
      title: pricingBuilder.title,
      subtitle: pricingBuilder.subtitle,
      plans: installPayload.plans,
    },
    null,
    2,
  )
  const safeHandle = pricingBuilder.handle.toLowerCase().replace(/[^a-z0-9-]/g, '-')
  return `${openTag}>\nwindow.PayGluePricing = ${payload};\n${closeTag}\n${openTag} src="https://dev.payglue.io/pricing-table.js" data-table="${safeHandle}" defer>${closeTag}\n<div id="payglue-pricing-table"></div>`
})

const installPayload = {
  title: 'PayGlue Pricing',
  subtitle: 'Transparent pricing for Ghost + Polar rollout.',
  plans: [
    {
      id: 'beta',
      name: 'Beta',
      price: 'Free',
      description: 'Early access while invite gate is active.',
      features: ['Join waitlist', 'Ghost entitlement sync', 'Early beta onboarding'],
      ctaLabel: 'Join Waitlist',
    },
    {
      id: 'founder',
      name: 'Founder',
      price: '$149',
      description: 'Founder access tier for early adopter teams.',
      features: ['Coexistence migration support', 'Webhook replay workflow', 'Priority onboarding support'],
      ctaLabel: 'Apply as Member',
    },
  ],
}

const openTag = '<' + 'script'
const closeTag = '</' + 'script>'

const scriptEmbedSnippet = `${openTag}>
window.PayGluePricing = ${JSON.stringify(installPayload, null, 2)};
${closeTag}
${openTag} src="https://dev.payglue.io/pricing-table.js" defer>${closeTag}
<div id="payglue-pricing-table"></div>`

const iframeEmbedSnippet = `<iframe src="https://dev.payglue.io/tennant/dev" style="width:100%;min-height:900px;border:0;" title="PayGlue pricing"></iframe>`
</script>

<template>
  <div class="min-h-screen bg-slate-50">
    <div class="flex min-h-screen">
      <aside class="hidden w-64 shrink-0 border-r border-slate-200 bg-white md:flex md:flex-col">
        <div class="flex items-center gap-3 border-b border-slate-200 px-4 py-4">
          <div class="grid h-9 w-9 place-items-center rounded-lg bg-blue-600 text-sm font-semibold text-white">GG</div>
          <div>
            <p class="text-sm font-semibold tracking-wide">PayGlue</p>
            <p class="text-xs text-slate-500">Dashboard preview</p>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto px-3 py-3">
          <nav v-for="group in previewNavGroups" :key="group.title" class="mb-4">
            <p class="px-2 pb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">{{ group.title }}</p>
            <a
              v-for="(link, index) in group.links"
              :key="`${group.title}-${link.label}`"
              :href="link.href"
              class="mb-1 block rounded-md px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
              :class="group.title === 'General' && index === 0 ? 'bg-blue-50 text-blue-700' : ''"
            >
              {{ link.label }}
            </a>
          </nav>

        </div>
      </aside>

      <main class="min-w-0 flex-1 px-4 py-6 sm:px-6">
        <div class="mx-auto max-w-7xl space-y-6">
          <header class="rounded-xl border border-slate-200 bg-white px-4 py-4 shadow-sm">
            <p class="text-xs font-semibold uppercase tracking-[0.14em] text-blue-600">Preview mode</p>
            <h1 class="mt-1 text-2xl font-semibold text-slate-900">PayGlue Dashboard Preview</h1>
            <p class="mt-1 text-sm text-slate-600">
              This is a non-auth preview so you can validate layout before Firebase auth is configured.
            </p>
          </header>

          <section id="dashboard" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <article
              v-for="card in kpiCards"
              :key="card.label"
              class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
            >
              <p class="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">{{ card.label }}</p>
              <p class="mt-2 text-3xl font-semibold text-slate-900">{{ card.value }}</p>
              <p class="mt-1 text-sm text-slate-500">{{ card.hint }}</p>
            </article>
          </section>

          <section id="connect-ghost" class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p class="text-xs font-semibold uppercase tracking-[0.14em] text-blue-600">Connect Ghost</p>
            <h2 class="mt-1 text-sm font-semibold text-slate-900">Ghost credentials (preview)</h2>
            <p class="mt-1 text-sm text-slate-600">This mirrors the backend connect form. Save in preview stores values in your browser only.</p>

            <div class="mt-4 grid gap-3 md:grid-cols-2">
              <label class="text-sm text-slate-700 md:col-span-2">
                <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Ghost Content API key</span>
                <input v-model="connectForm.contentApiKey" type="text" class="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm" placeholder="required" />
              </label>
              <label class="text-sm text-slate-700 md:col-span-2">
                <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Ghost Admin API key</span>
                <input v-model="connectForm.adminApiKey" type="text" class="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm" placeholder="&lt;id&gt;:&lt;hex-secret&gt;" />
              </label>
              <label class="text-sm text-slate-700 md:col-span-2">
                <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Ghost API URL</span>
                <input v-model="connectForm.apiUrl" type="text" class="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm" placeholder="http://ghost:2368/ghost/api/admin" />
              </label>
            </div>

            <div class="mt-4 flex flex-wrap gap-2">
              <button type="button" class="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700" @click="savePreviewConnect">Save credentials</button>
              <button type="button" class="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100" @click="runPreviewHealth">Run health check</button>
            </div>

            <p v-if="connectSuccess" class="mt-3 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{{ connectSuccess }}</p>
            <p v-if="connectError" class="mt-3 rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800">{{ connectError }}</p>
          </section>

          <section id="events" class="grid gap-4 xl:grid-cols-3">
            <article class="rounded-xl border border-slate-200 bg-white shadow-sm xl:col-span-2">
              <div class="border-b border-slate-200 px-4 py-3">
                <h2 class="text-sm font-semibold text-slate-900">Recent webhook events</h2>
              </div>
              <ul class="divide-y divide-slate-200">
                <li
                  v-for="event in events"
                  :key="event.id"
                  class="flex items-center justify-between gap-3 px-4 py-3 text-sm"
                >
                  <div>
                    <p class="font-medium text-slate-900">#{{ event.id }} · {{ event.provider }}</p>
                    <p class="text-xs text-slate-500">{{ event.createdAt }}</p>
                  </div>
                  <div class="text-right">
                    <p
                      class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"
                      :class="event.status === 'processed' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'"
                    >
                      {{ event.status }}
                    </p>
                    <p class="mt-1 text-xs text-slate-500">Attempts {{ event.attempts }}</p>
                  </div>
                </li>
              </ul>
            </article>

            <article class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 class="text-sm font-semibold text-slate-900">Integration health</h2>
              <ul class="mt-3 space-y-2 text-sm">
                <li class="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2">
                  <span>Payment provider</span><span class="text-emerald-700">Enabled</span>
                </li>
                <li class="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2">
                  <span>CMS provider</span><span class="text-emerald-700">Enabled</span>
                </li>
                <li class="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2">
                  <span>Tenant role</span><span class="text-slate-700">owner</span>
                </li>
              </ul>
            </article>
          </section>

          <section class="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div class="border-b border-slate-200 px-4 py-3">
              <h2 class="text-sm font-semibold text-slate-900">Recent audit activity</h2>
            </div>
            <ul class="divide-y divide-slate-200">
              <li v-for="item in audits" :key="`${item.type}-${item.id}`" class="px-4 py-3 text-sm">
                <p class="font-medium text-slate-900">{{ item.type }}</p>
                <p class="text-xs text-slate-500">{{ item.target }} · {{ item.id }} · {{ item.at }}</p>
              </li>
            </ul>
          </section>

          <section id="pricing-table" class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p class="text-xs font-semibold uppercase tracking-[0.14em] text-blue-600">Pricing Table</p>
            <h2 class="mt-1 text-sm font-semibold text-slate-900">Create pricing table snippet</h2>
            <p class="mt-1 text-sm text-slate-600">Configure heading and handle, then copy the snippet for Ghost embed.</p>

            <div class="mt-4 grid gap-3">
              <input v-model="pricingBuilder.title" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Pricing title" />
              <textarea v-model="pricingBuilder.subtitle" class="min-h-20 rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Pricing subtitle" />
              <input v-model="pricingBuilder.handle" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="Embed handle" />
            </div>

            <pre class="mt-3 overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100"><code>{{ pricingTableSnippet }}</code></pre>
          </section>

          <section class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" id="installation">
            <p class="text-xs font-semibold uppercase tracking-[0.14em] text-blue-600">Installation</p>
            <h2 class="mt-1 text-sm font-semibold text-slate-900">Pricing embed snippets</h2>
            <p class="mt-1 text-sm text-slate-600">
              Use these snippets to validate the pricing table render and prepare Polar integration wiring.
            </p>

            <h3 class="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Script embed</h3>
            <pre class="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100"><code>{{ scriptEmbedSnippet }}</code></pre>

            <h3 class="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Iframe fallback</h3>
            <pre class="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100"><code>{{ iframeEmbedSnippet }}</code></pre>

            <p class="mt-3 text-xs text-slate-500">
              Dev endpoint:
              <a
                class="font-medium text-blue-700 hover:underline"
                href="https://dev.payglue.io/tennant/dev"
                target="_blank"
                rel="noopener noreferrer"
              >
                https://dev.payglue.io/tennant/dev
              </a>
            </p>
          </section>
        </div>
      </main>
    </div>
  </div>
</template>

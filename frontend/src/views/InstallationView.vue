// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { useSessionStore } from '../stores/session'
import { useHeaderScriptStatus } from '../composables/useHeaderScriptStatus'
import { checkHeaderScript } from '../lib/api'

const session = useSessionStore()
const { isInstalled, markInstalled, markNotInstalled } = useHeaderScriptStatus()

const copied = ref(false)
const checking = ref(false)
const checkResult = ref<{ installed: boolean; url: string | null; error: string | null } | null>(null)

async function runCheck() {
  if (!session.activeTenantSlug || !session.idToken) return
  checking.value = true
  checkResult.value = null
  try {
    const result = await checkHeaderScript(session.activeTenantSlug, session.idToken)
    checkResult.value = result
    if (result.installed) markInstalled()
    else markNotInstalled()
  } catch (e: unknown) {
    checkResult.value = { installed: false, url: null, error: e instanceof Error ? e.message : 'Check failed.' }
  } finally {
    checking.value = false
  }
}

const headerScript = computed(() => {
  const slug = session.activeTenantSlug ?? 'YOUR-TENANT-SLUG'
  return `<script src="https://api.payglue.io/paywall.js"\n  data-org="${slug}"><\/script>`
})

async function copyScript() {
  await navigator.clipboard.writeText(headerScript.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

</script>

<template>
  <AppShell>
    <div class="space-y-6">

      <!-- Header -->
      <section class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <p class="text-xs font-semibold uppercase tracking-[0.12em] text-blue-600">Installation</p>
        <h1 class="mt-1 text-xl font-semibold text-slate-900">Header script</h1>
        <p class="mt-1 text-sm text-slate-600">
          One script tag added once to your Ghost site header. Required for the Paywall to work. Buttons and Pricing Tables have their own inline embed snippets on their respective pages.
        </p>
      </section>

      <!-- Script setup -->
      <section class="rounded-xl border-2 border-indigo-300 bg-indigo-50 p-5 shadow-sm space-y-4">
        <div class="flex items-center gap-2.5">
          <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-[11px] font-bold text-white">1</span>
          <h2 class="text-sm font-semibold text-indigo-900">Add to Ghost — Site Header</h2>
        </div>
        <p class="text-xs text-indigo-700">
          Go to Ghost Admin &rsaquo; Settings &rsaquo; Code Injection &rsaquo; Site Header and paste this script tag. Do this once — it never changes.
        </p>

        <div>
          <div class="flex items-center justify-between mb-1.5">
            <p class="text-xs font-medium text-indigo-800">Script tag</p>
            <button type="button"
              class="flex items-center gap-1 rounded border border-indigo-300 bg-white px-2 py-1 text-[11px] font-medium text-indigo-700 hover:bg-indigo-100"
              @click="copyScript">
              <svg v-if="!copied" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              <svg v-else class="h-3 w-3 text-emerald-500" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              {{ copied ? 'Copied' : 'Copy' }}
            </button>
          </div>
          <pre class="overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100"><code>{{ headerScript }}</code></pre>
        </div>

        <div class="rounded-lg border border-indigo-200 bg-white/60 p-3 text-xs text-indigo-600">
          Not suitable for highly confidential content — the overlay is client-side only. Content is visible in DevTools.
          <a href="https://docs.payglue.io/paywall/overview" target="_blank" rel="noopener noreferrer" class="underline hover:text-indigo-800">Learn more</a>
        </div>
      </section>

      <!-- Installation status -->
      <section class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        <div>
          <h2 class="text-sm font-semibold text-slate-900">Installation status</h2>
          <p class="mt-0.5 text-xs text-slate-500">
            Use the button below to verify automatically that the script is live on your Ghost site.
          </p>
        </div>

        <!-- Auto-check -->
        <div class="flex items-center gap-3">
          <button
            type="button"
            :disabled="checking"
            @click="runCheck"
            class="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-700 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50 transition-colors"
          >
            <svg v-if="!checking" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            <svg v-else class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
            {{ checking ? 'Checking...' : 'Check automatically' }}
          </button>

          <!-- Check result -->
          <span v-if="checkResult && checkResult.installed" class="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">
            <svg class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
            Found on {{ checkResult.url }}
          </span>
          <span v-else-if="checkResult && !checkResult.installed && !checkResult.error" class="rounded-full bg-rose-50 px-3 py-1 text-xs font-medium text-rose-700 ring-1 ring-rose-200">
            Script not found on {{ checkResult.url }}
          </span>
          <span v-else-if="checkResult && checkResult.error" class="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 ring-1 ring-amber-200">
            {{ checkResult.error }}
          </span>
        </div>

        <!-- Current status -->
        <div class="flex items-center gap-2">
          <span
            v-if="isInstalled"
            class="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200"
          >
            <svg class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
            Installed — script is active in Ghost
          </span>
          <span
            v-else
            class="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 ring-1 ring-amber-200"
          >
            Not installed — paste the script above into Ghost first
          </span>
        </div>
      </section>

      <!-- Other scripts info -->
      <section class="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 class="text-sm font-semibold text-slate-900 mb-3">Other embeds</h2>
        <div class="space-y-3">
          <div class="flex items-start gap-3 rounded-lg border border-slate-100 bg-slate-50 p-3">
            <svg class="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
            </svg>
            <div>
              <p class="text-xs font-medium text-slate-700">Buy Buttons</p>
              <p class="mt-0.5 text-xs text-slate-500">Each button has its own <code class="rounded bg-white px-1 py-0.5 ring-1 ring-slate-200">button.js</code> embed tag — paste it inline where you want the button to appear. No header install needed.</p>
            </div>
          </div>
          <div class="flex items-start gap-3 rounded-lg border border-slate-100 bg-slate-50 p-3">
            <svg class="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h1.5C5.496 19.5 6 18.996 6 18.375m-3.75.125v-4.25A.375.375 0 012.625 14h18.75c.207 0 .375.168.375.375v4.25m-19.5 0H21m0 0a1.125 1.125 0 001.125-1.125m-18 0v-4.5" />
            </svg>
            <div>
              <p class="text-xs font-medium text-slate-700">Pricing Table</p>
              <p class="mt-0.5 text-xs text-slate-500">The Pricing Table has its own inline embed snippet. Paste it on any page where you want the table rendered. No header install needed.</p>
            </div>
          </div>
        </div>
      </section>

    </div>
  </AppShell>
</template>

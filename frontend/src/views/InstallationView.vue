// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { PageHeader, UiCard, StatusPill } from '../components/ui'
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
    <div class="space-y-5">
      <PageHeader title="Header script" description="One script tag added once to your Ghost site header. Required for the Paywall to work. Buttons and Pricing Tables have their own inline embed snippets on their respective pages." />

      <!-- Script setup -->
      <section class="space-y-4 rounded-2xl border border-indigo-200 bg-indigo-50 p-5 shadow-sm dark:border-indigo-500/30 dark:bg-indigo-500/10">
        <div class="flex items-center gap-2.5">
          <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-[11px] font-bold text-white">1</span>
          <h2 class="text-sm font-semibold text-indigo-900 dark:text-indigo-200">Add to Ghost: Site Header</h2>
        </div>
        <p class="text-xs text-indigo-700 dark:text-indigo-300">
          Go to Ghost Admin &rsaquo; Settings &rsaquo; Code Injection &rsaquo; Site Header and paste this script tag. Do this once, it never changes.
        </p>

        <div>
          <div class="mb-1.5 flex items-center justify-between">
            <p class="text-xs font-medium text-indigo-800 dark:text-indigo-300">Script tag</p>
            <button type="button"
              class="flex items-center gap-1 rounded-lg border border-indigo-300 bg-white px-2 py-1 text-[11px] font-medium text-indigo-700 hover:bg-indigo-100 dark:border-indigo-500/40 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-indigo-500/10"
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
          <pre class="overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100 ring-1 ring-slate-800"><code>{{ headerScript }}</code></pre>
        </div>

        <div class="rounded-lg border border-indigo-200 bg-white/60 p-3 text-xs text-indigo-600 dark:border-indigo-500/30 dark:bg-slate-900/60 dark:text-indigo-300">
          Not suitable for highly confidential content: the overlay is client-side only. Content is visible in DevTools.
          <a href="https://docs.payglue.io/paywall/overview" target="_blank" rel="noopener noreferrer" class="underline hover:text-indigo-800 dark:hover:text-indigo-200">Learn more</a>
        </div>
      </section>

      <!-- Installation status -->
      <UiCard title="Installation status" description="Use the button below to verify automatically that the script is live on your Ghost site.">
        <div class="space-y-4">
          <div class="flex flex-wrap items-center gap-3">
            <button
              type="button"
              :disabled="checking"
              @click="runCheck"
              class="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-700 transition-colors hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:border-indigo-500/40 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-300"
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

            <StatusPill v-if="checkResult && checkResult.installed" tone="good">Found on {{ checkResult.url }}</StatusPill>
            <StatusPill v-else-if="checkResult && !checkResult.installed && !checkResult.error" tone="bad">Script not found on {{ checkResult.url }}</StatusPill>
            <StatusPill v-else-if="checkResult && checkResult.error" tone="warn">{{ checkResult.error }}</StatusPill>
          </div>

          <div class="flex items-center gap-2">
            <StatusPill v-if="isInstalled" tone="good" dot>Installed, script is active in Ghost</StatusPill>
            <StatusPill v-else tone="warn" dot>Not installed, paste the script above into Ghost first</StatusPill>
          </div>
        </div>
      </UiCard>

      <!-- Other scripts info -->
      <UiCard title="Other embeds">
        <div class="space-y-3">
          <div class="flex items-start gap-3 rounded-xl border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/40">
            <svg class="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
            </svg>
            <div>
              <p class="text-xs font-medium text-slate-700 dark:text-slate-200">Buy Buttons</p>
              <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Each button has its own <code class="rounded bg-white px-1 py-0.5 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">button.js</code> embed tag. Paste it inline where you want the button to appear. No header install needed.</p>
            </div>
          </div>
          <div class="flex items-start gap-3 rounded-xl border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/40">
            <svg class="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h1.5C5.496 19.5 6 18.996 6 18.375m-3.75.125v-4.25A.375.375 0 012.625 14h18.75c.207 0 .375.168.375.375v4.25m-19.5 0H21m0 0a1.125 1.125 0 001.125-1.125m-18 0v-4.5" />
            </svg>
            <div>
              <p class="text-xs font-medium text-slate-700 dark:text-slate-200">Pricing Table</p>
              <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">The Pricing Table has its own inline embed snippet. Paste it on any page where you want the table rendered. No header install needed.</p>
            </div>
          </div>
        </div>
      </UiCard>
    </div>
  </AppShell>
</template>

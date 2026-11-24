// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
// The quiet Turnstile slot used by every form in the dashboard. A status line
// of fixed height stands where the box used to be, so the form does not jump
// when the check finishes. The widget container stays collapsed (zero height,
// not display: none, which would stop the iframe from loading) until
// Cloudflare asks for an interaction, then it gets its room and the line goes.
//
// v-model carries the token; the parent calls reset() through a template ref
// after every submit, since a token is single use.

import { ref, watch } from 'vue'
import { useTurnstile } from '../composables/useTurnstile'

const props = withDefaults(defineProps<{ sitekey?: string; language?: string }>(), {
  sitekey: () => (import.meta.env.VITE_TURNSTILE_SITE_KEY as string | undefined) ?? '',
  // English like the rest of the app and the website, not the browser's language.
  language: 'en',
})

const token = defineModel<string | null>({ default: null })

const container = ref<HTMLElement | null>(null)
const { token: widgetToken, status, reset } = useTurnstile(container, {
  sitekey: props.sitekey,
  language: props.language,
})

// Synchronous on purpose. The composable drops the token while the component
// unmounts (Login switches to the password field, the form makes way for the
// code entry), and a deferred watcher would die before passing that on, so
// the parent would keep a spent token and an enabled button.
watch(
  widgetToken,
  (value) => {
    token.value = value
  },
  { flush: 'sync' },
)

defineExpose({ reset, status })
</script>

<template>
  <div v-if="status !== 'off'" data-testid="turnstile-check">
    <div
      ref="container"
      :class="status === 'interactive' ? '' : 'h-0 overflow-hidden'"
    />
    <p
      v-show="status !== 'interactive'"
      role="status"
      aria-live="polite"
      class="flex h-8 items-center gap-1.5 text-xs leading-4"
      :class="status === 'failed' ? 'text-rose-600' : 'text-slate-500'"
    >
      <svg
        v-if="status === 'passed'"
        xmlns="http://www.w3.org/2000/svg"
        class="h-3.5 w-3.5 flex-shrink-0 text-emerald-600"
        viewBox="0 0 20 20"
        fill="currentColor"
        aria-hidden="true"
      >
        <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
      </svg>
      <svg
        v-else-if="status === 'failed'"
        xmlns="http://www.w3.org/2000/svg"
        class="h-3.5 w-3.5 flex-shrink-0"
        viewBox="0 0 20 20"
        fill="currentColor"
        aria-hidden="true"
      >
        <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
      </svg>
      <svg
        v-else
        xmlns="http://www.w3.org/2000/svg"
        class="h-3.5 w-3.5 flex-shrink-0 motion-safe:animate-spin"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-opacity="0.25" stroke-width="3" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
      </svg>
      <span v-if="status === 'passed'">Security check passed</span>
      <span v-else-if="status === 'failed'">The security check didn't work. Please reload the page or try again in a moment.</span>
      <span v-else>Security check running in the background</span>
    </p>
  </div>
</template>

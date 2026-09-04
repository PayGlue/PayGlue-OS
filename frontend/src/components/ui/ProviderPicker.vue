// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
/**
 * The row of payment providers a widget can sell through.
 *
 * It exists because there are three widgets that need it: the buy button, the
 * paywall and each tier of a pricing table. Until now each of them carried its
 * own copy of the markup, and the copies had already drifted: the pills in the
 * pricing table were a size smaller than the other two. One component means the
 * three cannot disagree, which is a stronger promise than remembering to keep
 * them in step.
 *
 * The logo comes from `ProviderLogo`, the same one the Connections overview
 * uses. Eight colourless text pills read as a list to work through; eight marks
 * in their own brand colours are recognised without reading.
 *
 * Providers with no credentials are dimmed and say so. That is the part worth
 * more than the logo: today Patreon looks exactly like Polar even when picking
 * it leads to an empty product list, and "why is this dropdown empty" is a
 * support question we have already answered more than once.
 */
import { computed, onMounted, ref } from 'vue'
import ProviderLogo from './ProviderLogo.vue'
import { getIntegrationConfig } from '../../lib/api'
import { PROVIDER_BRAND } from '../../lib/providers'
import type { ProviderKey } from '../../lib/connectionProviders'
import { useSessionStore } from '../../stores/session'

/** Ghost is a CMS and Stripe is a special case, so neither sells anything here. */
const PAYMENT_PROVIDERS = [
  'polar',
  'lemonsqueezy',
  'paypal',
  'gumroad',
  'paddle',
  'kofi',
  'creem',
  'patreon',
] as const

const props = defineProps<{
  modelValue: string
  /** Defaults to every payment provider a widget can sell through. */
  providers?: readonly string[]
}>()

// Not a `withDefaults` factory: the compiler hoists `defineProps` out of
// setup(), so a default referencing a local constant is rejected outright.
const keys = computed(() => props.providers ?? PAYMENT_PROVIDERS)

const emit = defineEmits<{ 'update:modelValue': [string] }>()

const session = useSessionStore()
const connected = ref<Record<string, boolean>>({})

const name = (key: string) => PROVIDER_BRAND[key]?.name ?? key

onMounted(async () => {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  // Eight calls in parallel, the same way the Connections overview does it:
  // there is no endpoint that answers for all providers at once. Failures are
  // swallowed on purpose. Not knowing whether a provider is connected must
  // never stop somebody from choosing one.
  const results = await Promise.allSettled(
    keys.value.map(key => getIntegrationConfig(slug, token, key as ProviderKey)),
  )
  const next: Record<string, boolean> = {}
  keys.value.forEach((key, i) => {
    const r = results[i]
    next[key] = r.status === 'fulfilled' && Boolean(r.value.enabled)
  })
  connected.value = next
})
</script>

<template>
  <div class="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2">
    <button
      v-for="key in keys"
      :key="key"
      type="button"
      class="flex items-center gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors"
      :class="[
        modelValue === key
          ? 'border-2 border-indigo-500 bg-white dark:bg-slate-800'
          : 'border-slate-200 bg-white hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:hover:border-slate-600',
        connected[key] === false && modelValue !== key ? 'opacity-55' : '',
      ]"
      :aria-pressed="modelValue === key"
      @click="emit('update:modelValue', key)"
    >
      <ProviderLogo :provider="key" size="sm" />
      <span class="truncate text-sm text-slate-700 dark:text-slate-200">{{ name(key) }}</span>
      <svg
        v-if="modelValue === key"
        class="ml-auto h-4 w-4 shrink-0 text-indigo-500"
        viewBox="0 0 20 20"
        fill="currentColor"
        aria-hidden="true"
      >
        <path
          fill-rule="evenodd"
          d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0L3.3 9.7a1 1 0 011.4-1.4l3.8 3.8 6.8-6.8a1 1 0 011.4 0z"
          clip-rule="evenodd"
        />
      </svg>
      <span
        v-else-if="connected[key] === false"
        class="ml-auto shrink-0 whitespace-nowrap text-[11px] text-slate-400 dark:text-slate-500"
      >Not connected</span>
    </button>
  </div>
</template>

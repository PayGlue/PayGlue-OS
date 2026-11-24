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
  'paypal',
  'gumroad',
  'paddle',
  'kofi',
  'creem',
  'patreon',
  'dodo',
  'digistore24',
] as const

const props = defineProps<{
  modelValue: string
  /** Defaults to every payment provider a widget can sell through. */
  providers?: readonly string[]
}>()

// Not a `withDefaults` factory: the compiler hoists `defineProps` out of
// setup(), so a default referencing a local constant is rejected outright.
const allKeys = computed(() => props.providers ?? PAYMENT_PROVIDERS)
// Connected providers first, in their usual order, then the rest (PG-402).
// Stable: until the statuses load, the order stays as it was.
const keys = computed(() => {
  const list = allKeys.value
  return [...list.filter(key => connected.value[key] !== false), ...list.filter(key => connected.value[key] === false)]
})

const emit = defineEmits<{ 'update:modelValue': [string] }>()

const session = useSessionStore()
const connected = ref<Record<string, boolean>>({})

const name = (key: string) => PROVIDER_BRAND[key]?.name ?? key

// A widget saved with a provider that is no longer offered here (Lemon
// Squeezy, closing on 31 March 2027) matches none of the pills, so nothing
// looked selected while the products and the checkout link still came from
// that provider. Say so instead of leaving it to guesswork.
const RETIRED: Record<string, string> = {
  lemonsqueezy: 'This was set up with Lemon Squeezy, which PayGlue no longer supports because Lemon Squeezy is closing. Pick another provider and product below.',
}
const retiredNotice = computed(() =>
  props.modelValue && !allKeys.value.includes(props.modelValue) ? RETIRED[props.modelValue] ?? null : null,
)

onMounted(async () => {
  const slug = session.activeTenantSlug
  const token = session.idToken
  if (!slug || !token) return
  // Eight calls in parallel, the same way the Connections overview does it:
  // there is no endpoint that answers for all providers at once. Failures are
  // swallowed on purpose. Not knowing whether a provider is connected must
  // never stop somebody from choosing one.
  const results = await Promise.allSettled(
    allKeys.value.map(key => getIntegrationConfig(slug, token, key as ProviderKey)),
  )
  const next: Record<string, boolean> = {}
  allKeys.value.forEach((key, i) => {
    const r = results[i]
    next[key] = r.status === 'fulfilled' && Boolean(r.value.enabled)
  })
  connected.value = next
})
</script>

<template>
  <p
    v-if="retiredNotice"
    class="mb-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200"
  >
    {{ retiredNotice }}
  </p>
  <div class="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2">
    <button
      v-for="key in keys"
      :key="key"
      type="button"
      class="flex items-center gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
      :class="
        modelValue === key
          ? 'border-2 border-indigo-500 bg-white dark:bg-slate-800'
          : connected[key] === false
            ? 'border-dashed border-slate-300 bg-white hover:border-slate-400 dark:border-slate-600 dark:bg-slate-800/60 dark:hover:border-slate-500'
            : 'border-slate-200 bg-white hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:hover:border-slate-600'
      "
      :aria-pressed="modelValue === key"
      @click="emit('update:modelValue', key)"
    >
      <ProviderLogo :provider="key" size="sm" />
      <!-- Name above the status, so the name is never the part that gets cut
           off, and the tile stays fully readable (PG-402). -->
      <span class="flex min-w-0 flex-col">
        <span class="truncate text-sm text-slate-700 dark:text-slate-200">{{ name(key) }}</span>
        <span v-if="connected[key] === false && modelValue !== key" class="text-[11px] leading-tight text-slate-500 dark:text-slate-400">Not connected</span>
      </span>
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
    </button>
  </div>
</template>

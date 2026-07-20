// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed } from 'vue'

// Headline metric card: tinted icon, big number, label, sublabel, optional
// corner pill. Matches the Dashboard 2.0 stat row. `tint` picks the icon wash.
const props = withDefaults(
  defineProps<{
    value: string | number
    label: string
    sublabel?: string
    tint?: 'indigo' | 'sky' | 'violet' | 'emerald' | 'amber'
    to?: string
  }>(),
  { tint: 'indigo' },
)

const tintClass = computed(
  () =>
    ({
      indigo: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300',
      sky: 'bg-sky-50 text-sky-600 dark:bg-sky-500/15 dark:text-sky-300',
      violet: 'bg-violet-50 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300',
      emerald: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300',
      amber: 'bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300',
    })[props.tint],
)

const tag = computed(() => (props.to ? 'RouterLink' : 'div'))
</script>

<template>
  <component
    :is="tag"
    :to="to"
    class="group block rounded-2xl border border-slate-200 bg-white p-4 shadow-sm transition-transform hover:-translate-y-0.5 dark:border-slate-800 dark:bg-slate-900"
  >
    <div class="mb-4 flex items-start justify-between">
      <span class="flex h-10 w-10 items-center justify-center rounded-xl" :class="tintClass">
        <slot name="icon">
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8" /></svg>
        </slot>
      </span>
      <span v-if="$slots.badge" class="shrink-0"><slot name="badge" /></span>
    </div>
    <p class="text-3xl font-bold tracking-tight tabular-nums text-slate-900 dark:text-slate-100">{{ value }}</p>
    <p class="mt-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">{{ label }}</p>
    <p v-if="sublabel" class="mt-0.5 text-xs text-slate-400 dark:text-slate-500">{{ sublabel }}</p>
  </component>
</template>

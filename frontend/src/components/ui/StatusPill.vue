// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed } from 'vue'

// Semantic status chip. `tone` is separate from the indigo brand accent so
// good/warn/bad read at a glance in both light and dark.
const props = withDefaults(
  defineProps<{
    tone?: 'good' | 'warn' | 'bad' | 'neutral' | 'accent'
    /** Show a leading dot. */
    dot?: boolean
  }>(),
  { tone: 'neutral', dot: false },
)

const toneClass = computed(
  () =>
    ({
      good: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
      warn: 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
      bad: 'bg-rose-50 text-rose-600 dark:bg-rose-500/15 dark:text-rose-300',
      neutral: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
      accent: 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300',
    })[props.tone],
)
const dotClass = computed(
  () =>
    ({
      good: 'bg-emerald-500',
      warn: 'bg-amber-500',
      bad: 'bg-rose-500',
      neutral: 'bg-slate-400',
      accent: 'bg-indigo-500',
    })[props.tone],
)
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
    :class="toneClass"
  >
    <span v-if="dot" class="h-1.5 w-1.5 rounded-full" :class="dotClass" />
    <slot />
  </span>
</template>

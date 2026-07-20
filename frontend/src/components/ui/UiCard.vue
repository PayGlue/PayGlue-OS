// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
// The 2.0 surface: a rounded card with an optional titled header row.
// Colours (incl. dark) are written once here so every view inherits a
// consistent, fully theme-aware card without repeating `dark:` utilities.
withDefaults(
  defineProps<{
    title?: string
    description?: string
    /** Apply body padding. Turn off for full-bleed content like tables/lists. */
    padded?: boolean
  }>(),
  { padded: true },
)
</script>

<template>
  <section class="rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
    <header
      v-if="title || $slots.header || $slots.actions"
      class="flex items-start justify-between gap-3 px-5 pt-4"
      :class="$slots.default ? '' : 'pb-4'"
    >
      <slot name="header">
        <div class="min-w-0">
          <h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ title }}</h2>
          <p v-if="description" class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{{ description }}</p>
        </div>
      </slot>
      <div v-if="$slots.actions" class="shrink-0"><slot name="actions" /></div>
    </header>
    <div :class="padded ? 'p-5' : ''" :style="(title || $slots.header) && $slots.default ? 'padding-top:0.75rem' : ''">
      <slot />
    </div>
  </section>
</template>

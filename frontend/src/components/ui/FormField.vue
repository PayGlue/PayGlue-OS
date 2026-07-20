// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
// Label + optional "(optional)" marker + control slot + hint/error line.
// The input styling itself is provided by the shared `.pg-input` utility
// (see style.css) so plain <input>/<select> in a slot pick up the 2.0 look.
defineProps<{
  label?: string
  optional?: boolean
  hint?: string
  error?: string | null
}>()
</script>

<template>
  <div>
    <label v-if="label" class="mb-1.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">
      {{ label }}
      <span v-if="optional" class="font-normal normal-case tracking-normal text-slate-400 dark:text-slate-500">(optional)</span>
    </label>
    <slot />
    <p v-if="error" class="mt-1.5 text-xs text-rose-600 dark:text-rose-400">{{ error }}</p>
    <p v-else-if="hint" class="mt-1.5 text-xs leading-relaxed text-slate-400 dark:text-slate-500">{{ hint }}</p>
  </div>
</template>

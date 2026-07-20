// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
// Friendly empty placeholder: optional icon slot, title, message, action slot.
defineProps<{
  title: string
  message?: string
}>()
</script>

<template>
  <div class="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
    <span
      v-if="$slots.icon"
      class="mb-1 flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500"
    >
      <slot name="icon" />
    </span>
    <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ title }}</p>
    <p v-if="message" class="max-w-sm text-sm text-slate-500 dark:text-slate-400">{{ message }}</p>
    <div v-if="$slots.action" class="mt-2"><slot name="action" /></div>
  </div>
</template>

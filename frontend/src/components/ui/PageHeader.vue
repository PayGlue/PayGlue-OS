// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
// In-page title block for a view. The AppShell already renders a breadcrumb;
// this is the page's own heading + one-line description with an optional
// right-aligned action area (e.g. a "+ New" button).
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    <div class="min-w-0">
      <h1 class="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">{{ title }}</h1>
      <p v-if="description" class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="flex shrink-0 flex-wrap items-center gap-2"><slot name="actions" /></div>
  </div>
</template>

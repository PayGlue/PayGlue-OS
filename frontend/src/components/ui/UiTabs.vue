// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
// In-page segmented tabs (e.g. a provider filter). Distinct from the AppShell
// nav tabs. Controlled via v-model:modelValue against each tab's `key`.
defineProps<{
  modelValue: string
  tabs: { key: string; label: string }[]
}>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <div class="inline-flex items-center gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1 dark:border-slate-800 dark:bg-slate-900">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      type="button"
      class="rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
      :class="
        modelValue === tab.key
          ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-slate-100'
          : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'
      "
      @click="$emit('update:modelValue', tab.key)"
    >
      {{ tab.label }}
    </button>
  </div>
</template>

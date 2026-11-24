<!--
  Copyright (c) 2026 PayGlue by André Nünninghoff
  Licensed under the Business Source License 1.1, see LICENSE.md

  Footer row of a collapsed saved list: "Show 4 more" or "Show less".
-->
<script setup lang="ts">
defineProps<{ hiddenCount: number; canCollapse: boolean }>()
defineEmits<{ toggle: [] }>()
</script>

<template>
  <div v-if="hiddenCount > 0 || canCollapse" class="border-t border-slate-100 dark:border-slate-800">
    <button
      type="button"
      class="flex w-full items-center justify-center gap-1.5 rounded-b-2xl px-5 py-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50 hover:text-indigo-600 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-indigo-400"
      :aria-expanded="canCollapse"
      @click="$emit('toggle')"
    >
      {{ hiddenCount > 0 ? `Show ${hiddenCount} more` : 'Show less' }}
      <svg class="h-3.5 w-3.5 transition-transform" :class="canCollapse ? 'rotate-180' : ''" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="m6 9 6 6 6-6" />
      </svg>
    </button>
  </div>
</template>

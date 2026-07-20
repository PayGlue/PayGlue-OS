// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(defineProps<{ text: string; label?: string }>(), { label: 'Copy' })

const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

const copy = async () => {
  try {
    await navigator.clipboard.writeText(props.text)
  } catch {
    // Clipboard can reject (permissions / non-secure context); still flash
    // feedback so the button never feels unresponsive.
  }
  copied.value = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    copied.value = false
  }, 1800)
}
</script>

<template>
  <button
    type="button"
    class="inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors"
    :class="copied
      ? 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-300'
      : 'border-slate-300 text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800'"
    @click="copy"
  >
    <svg v-if="copied" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
      <path d="m5 13 4 4L19 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    {{ copied ? 'Copied' : label }}
  </button>
</template>

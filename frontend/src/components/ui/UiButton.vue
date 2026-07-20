// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed } from 'vue'

// Shared button. Renders as <button> by default, or <a>/<RouterLink> when
// `href`/`to` is given, so links and actions share one look. Dark handled once.
const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'default' | 'accent' | 'ghost' | 'danger'
    size?: 'sm' | 'md'
    type?: 'button' | 'submit'
    disabled?: boolean
    href?: string
    to?: string | Record<string, unknown>
    block?: boolean
  }>(),
  { variant: 'default', size: 'md', type: 'button', disabled: false, block: false },
)

const tag = computed(() => (props.to ? 'RouterLink' : props.href ? 'a' : 'button'))

const variantClass = computed(
  () =>
    ({
      primary:
        'border border-indigo-600 bg-indigo-600 text-white hover:bg-indigo-500 hover:border-indigo-500',
      default:
        'border border-slate-300 bg-white text-slate-700 hover:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-600',
      accent:
        'border border-indigo-200 bg-white text-indigo-600 hover:border-indigo-300 hover:bg-indigo-50 dark:border-indigo-500/40 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-indigo-500/10',
      ghost:
        'border border-transparent text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
      danger:
        'border border-rose-200 bg-white text-rose-600 hover:border-rose-300 hover:bg-rose-50 dark:border-rose-500/40 dark:bg-slate-900 dark:text-rose-300 dark:hover:bg-rose-500/10',
    })[props.variant],
)
const sizeClass = computed(() => (props.size === 'sm' ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm'))
</script>

<template>
  <component
    :is="tag"
    :to="to"
    :href="href"
    :type="tag === 'button' ? type : undefined"
    :disabled="tag === 'button' ? disabled : undefined"
    class="inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-xl font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50 dark:focus-visible:ring-offset-slate-900"
    :class="[variantClass, sizeClass, block ? 'w-full' : '']"
  >
    <slot />
  </component>
</template>

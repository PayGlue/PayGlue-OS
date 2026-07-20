// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed } from 'vue'
import { PROVIDER_BRAND } from '../../lib/providers'

const props = withDefaults(
  defineProps<{
    provider: string
    /** Chip edge length. */
    size?: 'sm' | 'md' | 'lg'
  }>(),
  { size: 'md' },
)

const brand = computed(() => PROVIDER_BRAND[props.provider])

const box = computed(() =>
  props.size === 'sm' ? 'h-8 w-8 rounded-lg' : props.size === 'lg' ? 'h-12 w-12 rounded-2xl' : 'h-10 w-10 rounded-xl',
)
const glyph = computed(() =>
  props.size === 'sm' ? 'h-4 w-4' : props.size === 'lg' ? 'h-6 w-6' : 'h-5 w-5',
)
</script>

<template>
  <span
    v-if="brand"
    class="inline-flex shrink-0 items-center justify-center"
    :class="[box, brand.border ? 'ring-1 ring-slate-200 dark:ring-slate-700' : '']"
    :style="{ backgroundColor: brand.chip }"
    :title="brand.name"
  >
    <img v-if="brand.kind === 'img'" :src="brand.img" :alt="brand.name" :class="glyph" />
    <svg v-else-if="brand.kind === 'polar'" viewBox="0 0 20 20" fill="none" :class="glyph">
      <circle cx="10" cy="10" r="8.4" :stroke="brand.fill" stroke-width="1.6" />
      <circle cx="10" cy="10" r="4.6" :stroke="brand.fill" stroke-width="1.6" />
    </svg>
    <svg v-else viewBox="0 0 24 24" :class="glyph">
      <path :fill="brand.fill" :d="brand.path" />
    </svg>
  </span>
  <!-- Fallback: a neutral monogram chip for an unknown provider key. -->
  <span
    v-else
    class="inline-flex shrink-0 items-center justify-center bg-slate-400 font-bold text-white dark:bg-slate-600"
    :class="box"
  >
    {{ provider.charAt(0).toUpperCase() }}
  </span>
</template>

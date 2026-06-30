// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
defineProps<{ size?: 'sm' | 'md' | 'lg'; dark?: boolean }>()
</script>

<template>
  <span class="inline-flex items-center gap-2.5">
    <span class="relative flex-shrink-0" :class="size === 'sm' ? 'h-5 w-5' : size === 'lg' ? 'h-10 w-10' : 'h-7 w-7'">
      <svg viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg" class="h-full w-full">
        <rect x="0" y="0" width="256" height="256" rx="58" fill="#5B5BD6"/>
        <circle cx="94" cy="128" r="62" fill="none" stroke="white" stroke-width="22" opacity="0.35"/>
        <circle cx="162" cy="128" r="62" fill="none" stroke="white" stroke-width="22"/>
        <rect x="114" y="66" width="28" height="124" fill="#5B5BD6"/>
        <rect x="119" y="102" width="18" height="52" rx="9" fill="white"/>
      </svg>
    </span>
    <span class="font-extrabold tracking-tight" :class="size === 'sm' ? 'text-sm' : size === 'lg' ? 'text-2xl' : 'text-base'">
      <span class="text-indigo-600">Pay</span><span :class="dark ? 'text-white' : 'text-slate-900'">Glue</span>
    </span>
  </span>
</template>

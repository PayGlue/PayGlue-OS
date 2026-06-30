// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import type { PricingPlan } from '../types/api'

defineProps<{
  title: string
  subtitle: string
  plans: PricingPlan[]
}>()
</script>

<template>
  <section class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    <div class="text-center">
      <h3 class="text-2xl font-semibold text-slate-900">{{ title }}</h3>
      <p class="mt-2 text-sm text-slate-600">{{ subtitle }}</p>
    </div>

    <div class="mt-6 grid gap-4 md:grid-cols-3">
      <article
        v-for="plan in plans"
        :key="plan.id"
        class="flex flex-col rounded-xl border border-slate-200 bg-gradient-to-b from-white to-slate-50 p-5"
      >
        <h4 class="text-lg font-semibold text-slate-900">{{ plan.name }}</h4>
        <p class="mt-1 text-3xl font-bold text-blue-700">{{ plan.price }}</p>
        <p class="mt-2 text-sm text-slate-600">{{ plan.description }}</p>

        <ul class="mt-4 space-y-2 text-sm text-slate-700">
          <li v-for="feature in plan.features" :key="feature" class="flex items-start gap-2">
            <span class="mt-1 h-1.5 w-1.5 rounded-full bg-emerald-500" />
            <span>{{ feature }}</span>
          </li>
        </ul>

        <button class="mt-6 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
          {{ plan.ctaLabel }}
        </button>
      </article>
    </div>
  </section>
</template>

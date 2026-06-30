// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'
import PayGlueLogo from '../components/PayGlueLogo.vue'

const session = useSessionStore()
const router = useRouter()

const openOrg = async (tenantSlug: string) => {
  session.setActiveTenant(tenantSlug)
  await router.push(`/t/${tenantSlug}/dashboard`)
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-slate-50 px-4">
    <section class="w-full max-w-lg">

      <div class="mb-8 text-center">
        <RouterLink to="/"><PayGlueLogo size="lg" /></RouterLink>
      </div>

      <div class="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 class="text-xl font-bold text-slate-900">Your organizations</h1>
        <p class="mt-1 text-sm text-slate-500">Select an organization to open its dashboard.</p>

        <div v-if="session.memberships.length === 0" class="mt-6 rounded-xl border border-slate-200 bg-slate-50 px-5 py-6 text-center">
          <p class="text-sm text-slate-500">No organization found for this account yet.</p>
          <RouterLink
            to="/tenant/create"
            class="mt-4 inline-block rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
          >
            Create your first organization
          </RouterLink>
        </div>

        <div v-else class="mt-6 space-y-2">
          <button
            v-for="membership in session.memberships"
            :key="membership.tenant_slug"
            class="flex w-full items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left transition-colors hover:border-indigo-200 hover:bg-indigo-50"
            @click="openOrg(membership.tenant_slug)"
          >
            <div>
              <p class="font-semibold text-slate-900">{{ membership.tenant_name }}</p>
              <p class="text-xs text-slate-400">{{ membership.tenant_slug }} · {{ membership.role }}</p>
            </div>
            <span class="text-sm font-semibold text-indigo-600">Open</span>
          </button>

          <RouterLink
            to="/tenant/create"
            class="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 px-4 py-3 text-sm text-slate-400 transition-colors hover:border-indigo-300 hover:text-indigo-600"
          >
            <span>+ Add organization</span>
          </RouterLink>
        </div>
      </div>

    </section>
  </div>
</template>

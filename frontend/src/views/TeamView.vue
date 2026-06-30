// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import {
  addTeamMember,
  listTeamMembers,
  removeTeamMember,
  updateTeamMemberRole,
} from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { TeamMember, TenantMembership } from '../types/api'

const session = useSessionStore()
const members = ref<TeamMember[]>([])
const loading = ref(false)
const errorMessage = ref<string | null>(null)

const form = reactive({
  email: '',
  firebase_uid: '',
  role: 'admin' as TenantMembership['role'],
})

const activeRole = computed(() => session.activeMembership?.role)
const canWrite = computed(() => activeRole.value === 'owner' || activeRole.value === 'admin')
const canAssignOwner = computed(() => activeRole.value === 'owner')

const roleOptions = computed(() => {
  const base: TenantMembership['role'][] = ['admin', 'billing_admin', 'support_readonly']
  if (canAssignOwner.value) {
    return ['owner', ...base] as TenantMembership['role'][]
  }
  return base as TenantMembership['role'][]
})

const canMutateMember = (member: TeamMember): boolean => {
  if (!canWrite.value) return false
  if (member.role === 'owner' && activeRole.value !== 'owner') return false
  return true
}

const editableRolesForMember = (member: TeamMember): TenantMembership['role'][] => {
  if (member.role === 'owner' && activeRole.value !== 'owner') {
    return ['owner']
  }
  return roleOptions.value
}

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) {
    throw new Error('Tenant context is missing.')
  }
  return { tenantSlug: session.activeTenantSlug, token: session.idToken }
}

const load = async () => {
  loading.value = true
  errorMessage.value = null
  try {
    const { tenantSlug, token } = context()
    members.value = await listTeamMembers(tenantSlug, token)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to load team members.'
  } finally {
    loading.value = false
  }
}

const invite = async () => {
  if (!canWrite.value) return
  if (!form.email && !form.firebase_uid) {
    errorMessage.value = 'Provide email or user ID for the member.'
    return
  }
  try {
    const { tenantSlug, token } = context()
    const created = await addTeamMember(tenantSlug, token, {
      email: form.email || undefined,
      firebase_uid: form.firebase_uid || undefined,
      role: form.role,
    })
    members.value = [...members.value, created]
    form.email = ''
    form.firebase_uid = ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to add team member.'
  }
}

const changeRole = async (member: TeamMember, role: TenantMembership['role']) => {
  if (!canMutateMember(member)) return
  try {
    const { tenantSlug, token } = context()
    const updated = await updateTeamMemberRole(tenantSlug, token, member.id, role)
    members.value = members.value.map((existing) => (existing.id === member.id ? updated : existing))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to update role.'
  }
}

const removeMember = async (member: TeamMember) => {
  if (!canMutateMember(member)) return
  try {
    const { tenantSlug, token } = context()
    await removeTeamMember(tenantSlug, token, member.id)
    members.value = members.value.filter((existing) => existing.id !== member.id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to remove member.'
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <div class="space-y-6">
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h1 class="text-xl font-semibold text-slate-900">Tenant team</h1>
        <p class="mt-1 text-sm text-slate-600">Manage tenant member roles and access boundaries.</p>

        <form class="mt-4 grid gap-3 md:grid-cols-3" @submit.prevent="invite">
          <input
            v-model="form.email"
            type="email"
            placeholder="member@example.com"
            class="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            v-model="form.firebase_uid"
            type="text"
            placeholder="user ID (optional)"
            class="rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <select v-model="form.role" class="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option v-for="role in roleOptions" :key="role" :value="role">
              {{ role }}
            </option>
          </select>
          <button
            type="submit"
            class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            :disabled="!canWrite"
          >
            Add member
          </button>
        </form>
      </section>

      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500">Current members</h2>
        <p v-if="loading" class="mt-4 text-sm text-slate-500">Loading team members...</p>
        <p v-if="errorMessage" class="mt-4 text-sm text-rose-700">{{ errorMessage }}</p>

        <ul v-if="!loading" class="mt-4 space-y-3">
          <li
            v-for="member in members"
            :key="member.id"
            class="grid gap-3 rounded-lg border border-slate-200 px-3 py-3 md:grid-cols-[1fr_auto_auto] md:items-center"
          >
            <div>
              <p class="font-medium text-slate-900">{{ member.email }}</p>
              <p class="text-xs text-slate-500">{{ member.firebase_uid }}</p>
            </div>
            <select
              class="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              :value="member.role"
              :disabled="!canMutateMember(member)"
              @change="changeRole(member, ($event.target as HTMLSelectElement).value as TenantMembership['role'])"
            >
              <option
                v-for="role in editableRolesForMember(member)"
                :key="`${member.id}-${role}`"
                :value="role"
              >
                {{ role }}
              </option>
            </select>
            <button
              class="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="!canMutateMember(member)"
              @click="removeMember(member)"
            >
              Remove
            </button>
          </li>
        </ul>
      </section>
    </div>
  </AppShell>
</template>

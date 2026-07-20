// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import UpgradeBanner from '../components/UpgradeBanner.vue'
import {
  addTeamMember,
  getOwnershipTransfer,
  listTeamMembers,
  ownershipTransferAction,
  removeTeamMember,
  requestOwnershipTransfer,
  updateTeamMemberRole,
  type OwnershipTransfer,
} from '../lib/api'
import { isPlanLimitError, planKeyFromError } from '../lib/planUpgrade'
import StepUpDialog from '../components/StepUpDialog.vue'
import { useSessionStore } from '../stores/session'
import type { TeamMember, TenantMembership } from '../types/api'

const session = useSessionStore()
const members = ref<TeamMember[]>([])
const loading = ref(false)
const errorMessage = ref<string | null>(null)
const errorMessagePlan = ref<string | null>(null)
const successMessage = ref<string | null>(null)

const form = reactive({
  email: '',
  role: 'admin' as TenantMembership['role'],
})

const activeRole = computed(() => session.activeMembership?.role)
const canWrite = computed(() => activeRole.value === 'owner' || activeRole.value === 'admin')

// PG-182: owner is never assigned directly -- it only moves via the confirmed
// ownership-transfer flow. So it's not an option in any role picker.
const roleOptions = computed(
  () => ['admin', 'billing_admin', 'support_readonly'] as TenantMembership['role'][],
)

const canMutateMember = (member: TeamMember): boolean => {
  if (!canWrite.value) return false
  if (member.role === 'owner') return false // the owner's role isn't editable here
  return true
}

const editableRolesForMember = (member: TeamMember): TenantMembership['role'][] => {
  if (member.role === 'owner') return ['owner']
  return roleOptions.value
}

const context = () => {
  if (!session.activeTenantSlug || !session.idToken) {
    throw new Error('Tenant context is missing.')
  }
  return { tenantSlug: session.activeTenantSlug, token: session.idToken }
}

const ROLE_LABELS: Record<string, string> = {
  owner: 'Owner',
  admin: 'Admin',
  billing_admin: 'Billing Admin',
  support_readonly: 'Support (read-only)',
}
const roleLabel = (role: string): string => ROLE_LABELS[role] ?? role

const ROLE_DESCRIPTIONS: { role: string; description: string }[] = [
  { role: 'Owner', description: 'Full access, including billing and deleting the publication. The only role that can grant or remove Owner.' },
  { role: 'Admin', description: 'Manages buy buttons, paywalls, pricing tables, connections, and team members. Cannot access billing or grant Owner.' },
  { role: 'Billing Admin', description: 'Manages billing and plan changes. Read-only everywhere else.' },
  { role: 'Support (read-only)', description: 'Can view everything but cannot make any changes.' },
]

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
  if (!form.email) {
    errorMessage.value = 'Enter the email address of the person you want to add.'
    errorMessagePlan.value = null
    successMessage.value = null
    return
  }
  try {
    const { tenantSlug, token } = context()
    const created = await addTeamMember(tenantSlug, token, {
      email: form.email || undefined,
      role: form.role,
    })
    members.value = [...members.value, created]
    successMessage.value = created.invited_new_account
      ? `Invite sent to ${created.email} . They'll get an email with a sign-in link.`
      : `${created.email} was added to the team.`
    form.email = ''
    errorMessage.value = null
    errorMessagePlan.value = null
  } catch (error) {
    successMessage.value = null
    errorMessage.value = error instanceof Error ? error.message : 'Unable to add team member.'
    errorMessagePlan.value = isPlanLimitError(error) ? planKeyFromError(error) : null
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

// PG-182: pending ownership transfer.
const pendingTransfer = ref<OwnershipTransfer | null>(null)
const transferBusy = ref(false)
const myEmail = computed(() => session.user?.email ?? '')
const iAmCurrentOwner = computed(() => pendingTransfer.value?.current_owner_email === myEmail.value)
const canRequestTransfer = computed(() => canWrite.value && !pendingTransfer.value)

const loadTransfer = async () => {
  try {
    const { tenantSlug, token } = context()
    pendingTransfer.value = (await getOwnershipTransfer(tenantSlug, token)).pending
  } catch { /* non-fatal: the banner just won't show */ }
}

const requestTransfer = async (member: TeamMember) => {
  if (!canRequestTransfer.value || member.role === 'owner') return
  if (!window.confirm(`Request transferring ownership to ${member.email}? The current owner must confirm it (email + login).`)) return
  try {
    const { tenantSlug, token } = context()
    pendingTransfer.value = await requestOwnershipTransfer(tenantSlug, token, member.id)
    successMessage.value = `Ownership transfer to ${member.email} requested. The current owner must confirm it under Team.`
    errorMessage.value = null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to request the transfer.'
  }
}

// PG-203: confirming hands ownership (and the billing relationship) to someone
// else, so it is the one action here that asks the owner to prove presence.
// Reject and cancel leave everything as it was and stay one click.
const showTransferStepUp = ref(false)

const actOnTransfer = async (
  action: 'confirm' | 'reject' | 'cancel',
  stepUpToken?: string,
) => {
  if (action === 'confirm' && !stepUpToken) {
    showTransferStepUp.value = true
    return
  }
  showTransferStepUp.value = false
  transferBusy.value = true
  try {
    const { tenantSlug, token } = context()
    await ownershipTransferAction(tenantSlug, token, action, stepUpToken)
    pendingTransfer.value = null
    successMessage.value =
      action === 'confirm'
        ? 'Ownership transferred. You are now Billing Admin. Reload to refresh your access.'
        : `Ownership transfer ${action === 'reject' ? 'rejected' : 'cancelled'}.`
    errorMessage.value = null
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Unable to update the transfer.'
  } finally {
    transferBusy.value = false
  }
}

onMounted(() => {
  load()
  loadTransfer()
})
</script>

<template>
  <AppShell>
    <div class="space-y-6">
      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">Publication team</h1>
        <p class="mt-1 text-sm text-slate-600 dark:text-slate-300">Manage publication member roles and access boundaries.</p>
        <p class="mt-1 text-xs text-slate-400 dark:text-slate-500">
          Already have a PayGlue account? They're added right away. New to PayGlue? We'll email them a sign-in link, no separate purchase needed, they join under this publication's plan.
        </p>

        <p v-if="successMessage" class="mt-3 rounded-lg border border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300">
          {{ successMessage }}
        </p>

        <!-- PG-182: pending ownership transfer -->
        <div v-if="pendingTransfer" class="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm dark:border-amber-500/30 dark:bg-amber-500/10">
          <p class="font-medium text-amber-900 dark:text-amber-200">Ownership transfer pending</p>
          <p class="mt-0.5 text-amber-800 dark:text-amber-300">
            Transfer to <strong>{{ pendingTransfer.new_owner_email }}</strong>, requested by {{ pendingTransfer.requested_by_email }}. On confirm, the current owner becomes Billing Admin (billing stays with them).
          </p>
          <div class="mt-2.5 flex flex-wrap items-center gap-2">
            <template v-if="iAmCurrentOwner">
              <button type="button" :disabled="transferBusy" class="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50" @click="actOnTransfer('confirm')">Confirm transfer</button>
              <button type="button" :disabled="transferBusy" class="rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50 dark:border-rose-500/40 dark:text-rose-300 dark:hover:bg-rose-500/10" @click="actOnTransfer('reject')">Reject</button>
            </template>
            <template v-else>
              <span class="text-xs text-amber-700 dark:text-amber-400">Awaiting confirmation from the current owner ({{ pendingTransfer.current_owner_email }}).</span>
              <button v-if="canWrite" type="button" :disabled="transferBusy" class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" @click="actOnTransfer('cancel')">Cancel request</button>
            </template>
          </div>
        </div>

        <form class="mt-4 grid gap-3 md:grid-cols-2" @submit.prevent="invite">
          <input
            v-model="form.email"
            type="email"
            placeholder="member@example.com"
            class="rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm"
          />
          <select v-model="form.role" class="rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm">
            <option v-for="role in roleOptions" :key="role" :value="role">
              {{ roleLabel(role) }}
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

        <dl class="mt-5 grid gap-2.5 border-t border-slate-100 dark:border-slate-800 pt-4 sm:grid-cols-2">
          <div v-for="item in ROLE_DESCRIPTIONS" :key="item.role">
            <dt class="text-xs font-semibold text-slate-700 dark:text-slate-200">{{ item.role }}</dt>
            <dd class="text-xs text-slate-500 dark:text-slate-400">{{ item.description }}</dd>
          </div>
        </dl>
      </section>

      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Current members</h2>
        <p v-if="loading" class="mt-4 text-sm text-slate-500 dark:text-slate-400">Loading team members...</p>
        <UpgradeBanner v-if="errorMessage && errorMessagePlan" class="mt-4" :message="errorMessage" :plan-key="errorMessagePlan" />
        <p v-else-if="errorMessage" class="mt-4 text-sm text-rose-700 dark:text-rose-300">{{ errorMessage }}</p>

        <ul v-if="!loading" class="mt-4 space-y-3">
          <li
            v-for="member in members"
            :key="member.id"
            class="grid gap-3 rounded-lg border border-slate-200 dark:border-slate-800 px-3 py-3 md:grid-cols-[1fr_auto_auto] md:items-center"
          >
            <div>
              <p class="font-medium text-slate-900 dark:text-slate-100">{{ member.email }}</p>
              <p class="text-xs text-slate-500 dark:text-slate-400">{{ member.firebase_uid }}</p>
            </div>
            <select
              class="rounded-md border border-slate-300 dark:border-slate-700 px-2 py-1.5 text-sm"
              :value="member.role"
              :disabled="!canMutateMember(member)"
              @change="changeRole(member, ($event.target as HTMLSelectElement).value as TenantMembership['role'])"
            >
              <option
                v-for="role in editableRolesForMember(member)"
                :key="`${member.id}-${role}`"
                :value="role"
              >
                {{ roleLabel(role) }}
              </option>
            </select>
            <div class="flex items-center gap-2">
              <button
                v-if="canRequestTransfer && member.role !== 'owner'"
                type="button"
                class="rounded-md border border-indigo-200 px-3 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-50 dark:border-indigo-500/40 dark:text-indigo-300 dark:hover:bg-indigo-500/10"
                title="Requires the current owner to confirm"
                @click="requestTransfer(member)"
              >
                Make owner
              </button>
              <button
                class="rounded-md border border-slate-300 dark:border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="!canMutateMember(member)"
                @click="removeMember(member)"
              >
                Remove
              </button>
            </div>
          </li>
        </ul>
      </section>
    </div>
  </AppShell>
  <StepUpDialog
    :open="showTransferStepUp"
    purpose="owner_transfer"
    title="Confirm the ownership transfer"
    description="The new owner takes over billing and full access to this workspace. You become Billing Admin."
    confirm-label="Transfer ownership"
    @confirmed="(t) => actOnTransfer('confirm', t)"
    @close="showTransferStepUp = false"
  />
</template>
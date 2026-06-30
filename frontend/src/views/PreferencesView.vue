// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import { useSessionStore } from '../stores/session'
import { supabase } from '../lib/supabase'

const session = useSessionStore()

// --- Personal Information ---
const savingProfile = ref(false)
const profileSuccess = ref<string | null>(null)
const profileError = ref<string | null>(null)

const profile = reactive({
  first_name: '',
  last_name: '',
})

const loadProfile = () => {
  const meta = session.user?.user_metadata ?? {}
  profile.first_name = (meta.first_name as string) ?? ''
  profile.last_name = (meta.last_name as string) ?? ''
}

const saveProfile = async () => {
  savingProfile.value = true
  profileSuccess.value = null
  profileError.value = null
  try {
    const { error } = await supabase.auth.updateUser({
      data: { first_name: profile.first_name, last_name: profile.last_name },
    })
    if (error) throw error
    profileSuccess.value = 'Profile saved.'
  } catch (e) {
    profileError.value = e instanceof Error ? e.message : 'Could not save profile.'
  } finally {
    savingProfile.value = false
  }
}

// --- Authentication ---
const userEmail = computed(() => session.user?.email ?? '—')

const changingEmail = ref(false)
const showEmailChange = ref(false)
const newEmail = ref('')
const emailChangeSuccess = ref<string | null>(null)
const emailChangeError = ref<string | null>(null)

const requestEmailChange = async () => {
  emailChangeSuccess.value = null
  emailChangeError.value = null
  if (!newEmail.value) return
  changingEmail.value = true
  try {
    const { error } = await supabase.auth.updateUser({ email: newEmail.value })
    if (error) throw error
    emailChangeSuccess.value = `Verification sent to ${newEmail.value}. Check your inbox to confirm the change.`
    newEmail.value = ''
    showEmailChange.value = false
  } catch (e) {
    emailChangeError.value = e instanceof Error ? e.message : 'Could not request email change.'
  } finally {
    changingEmail.value = false
  }
}

// --- Danger Zone ---
const showDeleteDialog = ref(false)
const deleteConfirmInput = ref('')
const deleting = ref(false)
const deleteError = ref<string | null>(null)

const deleteConfirmMatch = computed(
  () => deleteConfirmInput.value.trim().toLowerCase() === userEmail.value.toLowerCase(),
)

const deleteAccount = async () => {
  if (!deleteConfirmMatch.value) return
  deleting.value = true
  deleteError.value = null
  try {
    const { error } = await supabase.auth.signOut()
    if (error) throw error
    // Full cascade deletion (Polar cancel, tenant data) requires backend endpoint — contact us for now.
    window.location.href = '/?deleted=1'
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : 'Could not delete account.'
    deleting.value = false
  }
}

onMounted(loadProfile)
</script>

<template>
  <AppShell>
    <div class="space-y-6">

      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h1 class="text-xl font-semibold text-slate-900">Preferences</h1>
        <p class="mt-1 text-sm text-slate-500">Account settings and personal information.</p>
      </section>

      <!-- Personal Information -->
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 class="mb-1 text-base font-semibold text-slate-900">Personal information</h2>
        <p class="mb-4 text-sm text-slate-500">Optional. Used for personalisation within the app.</p>

        <p v-if="profileError" class="mb-3 text-sm text-rose-700">{{ profileError }}</p>
        <p v-if="profileSuccess" class="mb-3 text-sm text-emerald-700">{{ profileSuccess }}</p>

        <form class="grid gap-3 sm:grid-cols-2" @submit.prevent="saveProfile">
          <label class="text-sm text-slate-700">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">First name</span>
            <input
              v-model="profile.first_name"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
              placeholder="Ada"
            />
          </label>
          <label class="text-sm text-slate-700">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Last name</span>
            <input
              v-model="profile.last_name"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
              placeholder="Lovelace"
            />
          </label>
          <button
            type="submit"
            class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 sm:col-span-2 sm:justify-self-start"
            :disabled="savingProfile"
          >
            {{ savingProfile ? 'Saving...' : 'Save' }}
          </button>
        </form>
      </section>

      <!-- Authentication Methods -->
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 class="mb-4 text-base font-semibold text-slate-900">Authentication Methods</h2>

        <p v-if="emailChangeError" class="mb-3 text-sm text-rose-700">{{ emailChangeError }}</p>
        <p v-if="emailChangeSuccess" class="mb-3 text-sm text-emerald-700">{{ emailChangeSuccess }}</p>

        <div class="divide-y divide-slate-100 rounded-xl border border-slate-200 overflow-hidden">

          <!-- GitHub (coming soon) -->
          <div class="flex items-center gap-4 px-4 py-3.5 opacity-50">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-slate-900">
              <svg class="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.477 2 2 6.477 2 12c0 4.418 2.865 8.166 6.839 9.489.5.092.682-.217.682-.483 0-.237-.009-.868-.013-1.703-2.782.604-3.369-1.342-3.369-1.342-.454-1.155-1.11-1.463-1.11-1.463-.908-.62.069-.607.069-.607 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.268 2.75 1.026A9.578 9.578 0 0112 6.836a9.59 9.59 0 012.504.337c1.909-1.294 2.747-1.026 2.747-1.026.546 1.377.203 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.579.688.481C19.138 20.163 22 16.418 22 12c0-5.523-4.477-10-10-10z"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900">GitHub</p>
              <p class="text-xs text-slate-500">Sign in with your GitHub account.</p>
            </div>
            <span class="flex-shrink-0 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-500">Coming soon</span>
          </div>

          <!-- Google (coming soon) -->
          <div class="flex items-center gap-4 px-4 py-3.5 opacity-50">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-slate-900">
              <svg class="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor">
                <path d="M21.35 11.1H12v2.9h5.35c-.23 1.22-.94 2.25-2 2.95v2.45h3.24c1.9-1.75 3-4.33 3-7.3 0-.7-.07-1.37-.24-2z"/>
                <path d="M12 22c2.7 0 4.96-.9 6.62-2.43l-3.24-2.52c-.9.6-2.04.96-3.38.96-2.6 0-4.8-1.76-5.6-4.12H3.06v2.6C4.7 19.93 8.1 22 12 22z"/>
                <path d="M6.4 13.89A6.08 6.08 0 016.1 12c0-.66.12-1.3.3-1.89V7.51H3.06A10.02 10.02 0 002 12c0 1.6.38 3.12 1.06 4.49l3.34-2.6z"/>
                <path d="M12 5.88c1.47 0 2.79.5 3.83 1.5l2.87-2.87C16.96 2.9 14.7 2 12 2 8.1 2 4.7 4.07 3.06 7.51l3.34 2.6C7.2 7.64 9.4 5.88 12 5.88z"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900">Google</p>
              <p class="text-xs text-slate-500">Sign in with your Google account.</p>
            </div>
            <span class="flex-shrink-0 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-500">Coming soon</span>
          </div>

          <!-- Apple (coming soon) -->
          <div class="flex items-center gap-4 px-4 py-3.5 opacity-50">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-slate-900">
              <svg class="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor">
                <path d="M17.05 20.28c-.98.95-2.05.8-3.08.35-1.09-.46-2.09-.48-3.24 0-1.44.62-2.2.44-3.06-.35C2.79 15.25 3.51 7.7 9.05 7.4c1.39.07 2.35.74 3.15.8 1.2-.24 2.35-.93 3.64-.84 1.54.12 2.71.74 3.48 1.87-3.17 1.87-2.42 5.97.48 7.12-.57 1.5-1.32 2.99-2.75 3.93zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900">Apple</p>
              <p class="text-xs text-slate-500">Sign in with your Apple ID.</p>
            </div>
            <span class="flex-shrink-0 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-500">Coming soon</span>
          </div>

          <!-- Email / OTP -->
          <div class="flex items-center gap-4 px-4 py-3.5">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white">
              <svg class="h-4 w-4 text-slate-700" viewBox="0 0 24 24" fill="none">
                <path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900">{{ userEmail }}</p>
              <p class="text-xs text-slate-500">You can sign in with OTP codes sent to your email.</p>
            </div>
            <button
              class="flex-shrink-0 rounded-full bg-slate-900 px-4 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 transition-colors"
              @click="showEmailChange = !showEmailChange"
            >
              Change Email
            </button>
          </div>

          <!-- Email change inline -->
          <div v-if="showEmailChange" class="bg-slate-50 px-4 py-4">
            <div class="flex gap-2">
              <input
                v-model="newEmail"
                type="email"
                placeholder="new@example.com"
                class="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
              />
              <button
                class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                :disabled="changingEmail || !newEmail"
                @click="requestEmailChange"
              >
                {{ changingEmail ? 'Sending...' : 'Send verification' }}
              </button>
            </div>
          </div>

        </div>
      </section>

      <!-- Two-Factor Authentication -->
      <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 class="mb-4 text-base font-semibold text-slate-900">Two-Factor Authentication</h2>

        <div class="divide-y divide-slate-100 rounded-xl border border-slate-200 overflow-hidden">
          <div class="flex items-center gap-4 px-4 py-3.5 opacity-50">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white">
              <svg class="h-4 w-4 text-slate-700" viewBox="0 0 24 24" fill="none">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900">Authenticator App</p>
              <p class="text-xs text-slate-500">Add an extra layer of security when you sign in.</p>
            </div>
            <span class="flex-shrink-0 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-500">Coming soon</span>
          </div>
        </div>
      </section>

      <!-- Danger Zone -->
      <section class="rounded-2xl border border-rose-100 bg-white p-5 shadow-sm">
        <h2 class="mb-1 text-base font-semibold text-rose-700">Danger zone</h2>
        <p class="mb-4 text-sm text-slate-500">
          Irreversible actions. Deleting your account removes all organizations, webhook configurations, and event history permanently.
        </p>
        <button
          class="rounded-lg border border-rose-200 px-4 py-2 text-sm font-semibold text-rose-600 hover:bg-rose-50"
          @click="showDeleteDialog = true"
        >
          Delete account
        </button>
      </section>

      <!-- Delete confirmation dialog -->
      <Teleport to="body">
        <div
          v-if="showDeleteDialog"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          @click.self="showDeleteDialog = false"
        >
          <div class="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 class="mb-2 text-base font-semibold text-slate-900">Delete account permanently?</h3>
            <p class="mb-4 text-sm text-slate-500">
              This will remove all your organizations, integrations, webhook events, and product mappings. Your Polar subscription will need to be cancelled separately.
            </p>
            <p class="mb-1 text-xs font-semibold text-slate-600">
              Type your email address to confirm:
              <span class="font-mono text-slate-800">{{ userEmail }}</span>
            </p>
            <input
              v-model="deleteConfirmInput"
              type="email"
              class="mb-4 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rose-300"
              placeholder="your@email.com"
            />
            <p v-if="deleteError" class="mb-3 text-sm text-rose-700">{{ deleteError }}</p>
            <div class="flex gap-3">
              <button
                class="flex-1 rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                @click="showDeleteDialog = false"
              >
                Cancel
              </button>
              <button
                class="flex-1 rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-40"
                :disabled="!deleteConfirmMatch || deleting"
                @click="deleteAccount"
              >
                {{ deleting ? 'Deleting...' : 'Delete my account' }}
              </button>
            </div>
          </div>
        </div>
      </Teleport>

    </div>
  </AppShell>
</template>

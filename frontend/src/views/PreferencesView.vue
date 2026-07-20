// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import StepUpDialog from '../components/StepUpDialog.vue'
import { useSessionStore } from '../stores/session'
import { useRouter } from 'vue-router'
import { supabase } from '../lib/supabase'
import {
  deleteAccount as deleteAccountApi,
  generateMfaBackupCodes,
  getMfaBackupCodesStatus,
} from '../lib/api'

const session = useSessionStore()
const router = useRouter()

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

// --- Linked social accounts ---
type OAuthProvider = 'google' | 'github'
const linkedProviders = ref<Set<OAuthProvider>>(new Set())
const linkingProvider = ref<OAuthProvider | null>(null)
const unlinkingProvider = ref<OAuthProvider | null>(null)
const linkError = ref<string | null>(null)

const loadIdentities = async () => {
  const { data, error } = await supabase.auth.getUserIdentities()
  if (error || !data) return
  linkedProviders.value = new Set(
    data.identities
      .map((identity) => identity.provider)
      .filter((provider): provider is OAuthProvider => provider === 'google' || provider === 'github'),
  )
}

// Supabase requires "Allow manual linking" enabled in the project's auth
// settings for linkIdentity() to work while already signed in.
const linkProvider = async (provider: OAuthProvider) => {
  linkError.value = null
  linkingProvider.value = provider
  const { error } = await supabase.auth.linkIdentity({
    provider,
    options: { redirectTo: `${window.location.origin}/auth/callback` },
  })
  if (error) {
    linkError.value = error.message
    linkingProvider.value = null
  }
  // On success the browser navigates away to the provider's consent screen.
}

const unlinkProvider = async (provider: OAuthProvider) => {
  linkError.value = null
  unlinkingProvider.value = provider
  try {
    const { data, error } = await supabase.auth.getUserIdentities()
    if (error || !data) throw error ?? new Error('Could not load linked accounts.')
    const identity = data.identities.find((i) => i.provider === provider)
    if (!identity) return
    const { error: unlinkError } = await supabase.auth.unlinkIdentity(identity)
    if (unlinkError) throw unlinkError
    await loadIdentities()
  } catch (e) {
    linkError.value = e instanceof Error ? e.message : 'Could not disconnect account.'
  } finally {
    unlinkingProvider.value = null
  }
}

// --- Two-Factor Authentication (TOTP via Supabase MFA) ---
type MfaStep = 'idle' | 'enrolling' | 'backup-codes'
const mfaStep = ref<MfaStep>('idle')
const mfaEnabled = ref(false)
const mfaFactorId = ref<string | null>(null)
const mfaQrSvg = ref<string | null>(null)
const mfaSecret = ref<string | null>(null)
const mfaVerifyCode = ref('')
const mfaError = ref<string | null>(null)
const mfaBusy = ref(false)
const backupCodes = ref<string[]>([])
const backupCodesConfirmed = ref(false)
const backupCodesRemaining = ref<number | null>(null)

const hasNoSocialProvider = computed(
  () => !linkedProviders.value.has('google') && !linkedProviders.value.has('github'),
)

const loadMfaStatus = async () => {
  const { data, error } = await supabase.auth.mfa.listFactors()
  if (error || !data) return
  const totp = data.totp.find((f) => f.status === 'verified')
  mfaEnabled.value = !!totp
  mfaFactorId.value = totp?.id ?? null
  if (totp && session.idToken) {
    try {
      const result = await getMfaBackupCodesStatus(session.idToken)
      backupCodesRemaining.value = result.remaining
    } catch {
      backupCodesRemaining.value = null
    }
  }
}

const startMfaEnrollment = async () => {
  mfaError.value = null
  mfaBusy.value = true
  try {
    const { data, error } = await supabase.auth.mfa.enroll({ factorType: 'totp' })
    if (error) throw error
    mfaFactorId.value = data.id
    mfaQrSvg.value = data.totp.qr_code
    mfaSecret.value = data.totp.secret
    mfaVerifyCode.value = ''
    mfaStep.value = 'enrolling'
  } catch (e) {
    mfaError.value = e instanceof Error ? e.message : 'Could not start 2FA setup.'
  } finally {
    mfaBusy.value = false
  }
}

const confirmMfaEnrollment = async () => {
  if (!mfaFactorId.value || mfaVerifyCode.value.trim().length < 6) return
  mfaError.value = null
  mfaBusy.value = true
  try {
    const { data: challenge, error: challengeError } = await supabase.auth.mfa.challenge({
      factorId: mfaFactorId.value,
    })
    if (challengeError) throw challengeError
    const { error: verifyError } = await supabase.auth.mfa.verify({
      factorId: mfaFactorId.value,
      challengeId: challenge.id,
      code: mfaVerifyCode.value.trim(),
    })
    if (verifyError) throw verifyError

    if (!session.idToken) throw new Error('Session expired, please sign in again.')
    const result = await generateMfaBackupCodes(session.idToken)
    backupCodes.value = result.codes
    backupCodesConfirmed.value = false
    mfaStep.value = 'backup-codes'
    mfaVerifyCode.value = ''
  } catch (e) {
    mfaError.value = e instanceof Error ? e.message : 'Invalid code. Please try again.'
  } finally {
    mfaBusy.value = false
  }
}

const cancelMfaEnrollment = async () => {
  if (mfaFactorId.value) {
    await supabase.auth.mfa.unenroll({ factorId: mfaFactorId.value })
  }
  mfaStep.value = 'idle'
  mfaFactorId.value = null
  mfaQrSvg.value = null
  mfaSecret.value = null
  mfaVerifyCode.value = ''
  mfaError.value = null
}

const finishMfaSetup = async () => {
  mfaStep.value = 'idle'
  mfaQrSvg.value = null
  mfaSecret.value = null
  backupCodes.value = []
  await loadMfaStatus()
}

const disableMfa = async () => {
  if (!mfaFactorId.value) return
  mfaError.value = null
  mfaBusy.value = true
  try {
    const { error } = await supabase.auth.mfa.unenroll({ factorId: mfaFactorId.value })
    if (error) throw error
    mfaEnabled.value = false
    mfaFactorId.value = null
    backupCodesRemaining.value = null
  } catch (e) {
    mfaError.value = e instanceof Error ? e.message : 'Could not disable 2FA.'
  } finally {
    mfaBusy.value = false
  }
}

const regenerateBackupCodes = async () => {
  if (!session.idToken) return
  mfaError.value = null
  mfaBusy.value = true
  try {
    const result = await generateMfaBackupCodes(session.idToken)
    backupCodes.value = result.codes
    backupCodesConfirmed.value = false
    mfaStep.value = 'backup-codes'
  } catch (e) {
    mfaError.value = e instanceof Error ? e.message : 'Could not generate backup codes.'
  } finally {
    mfaBusy.value = false
  }
}

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

// Typing the email address is the "did you mean this" gate. It is not proof of
// identity, so it hands over to the step-up dialog rather than deleting.
const showStepUp = ref(false)

const askForConfirmation = () => {
  if (!deleteConfirmMatch.value) return
  deleteError.value = null
  showDeleteDialog.value = false
  showStepUp.value = true
}

// Until PG-203 this function called supabase.auth.signOut() and redirected to
// /?deleted=1. Nothing was ever deleted: the account, its tenants and its Ghost
// credentials all survived, while the user was told their data was gone. The
// backend now really deletes, and only with a spent step-up grant.
const performDelete = async (stepUpToken: string) => {
  showStepUp.value = false
  deleting.value = true
  deleteError.value = null
  try {
    await deleteAccountApi(session.idToken!, stepUpToken)
    // Leave the protected route *before* signing out. App.vue redirects to
    // /login on SIGNED_OUT whenever the current route requires auth, and
    // Preferences does -- so signing out first raced that redirect against
    // this one and the goodbye page lost. /goodbye is public, so once we are
    // standing on it the sign-out handler has nothing to do.
    //
    // hasRoute rather than a hard reference: GoodbyeView is a hosted-PayGlue
    // page (it carries our own win-back copy and a mailto to André) and is not
    // synced to the open-source repo, whose router therefore has no such
    // route. Self-hosters land on the login page instead of a dead link, and
    // nobody has to remember to patch a second router by hand.
    await router.replace(router.hasRoute('goodbye') ? { name: 'goodbye' } : { name: 'login' })
    // The auth user is gone server-side; clear the local session so the app
    // does not keep a token for an account that no longer exists.
    await supabase.auth.signOut()
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : 'Could not delete account.'
    deleting.value = false
    showDeleteDialog.value = true
  }
}

onMounted(() => {
  loadProfile()
  loadIdentities()
  loadMfaStatus()
})
</script>

<template>
  <AppShell>
    <div class="space-y-6">

      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h1 class="text-xl font-semibold text-slate-900 dark:text-slate-100">Preferences</h1>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Account settings and personal information.</p>
      </section>

      <!-- Personal Information -->
      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="mb-1 text-base font-semibold text-slate-900 dark:text-slate-100">Personal information</h2>
        <p class="mb-4 text-sm text-slate-500 dark:text-slate-400">Optional. Used for personalisation within the app.</p>

        <p v-if="profileError" class="mb-3 text-sm text-rose-700 dark:text-rose-300">{{ profileError }}</p>
        <p v-if="profileSuccess" class="mb-3 text-sm text-emerald-700 dark:text-emerald-300">{{ profileSuccess }}</p>

        <form class="grid gap-3 sm:grid-cols-2" @submit.prevent="saveProfile">
          <label class="text-sm text-slate-700 dark:text-slate-200">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">First name</span>
            <input
              v-model="profile.first_name"
              class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
              placeholder="Ada"
            />
          </label>
          <label class="text-sm text-slate-700 dark:text-slate-200">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Last name</span>
            <input
              v-model="profile.last_name"
              class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
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
      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="mb-4 text-base font-semibold text-slate-900 dark:text-slate-100">Authentication Methods</h2>

        <p v-if="emailChangeError" class="mb-3 text-sm text-rose-700 dark:text-rose-300">{{ emailChangeError }}</p>
        <p v-if="emailChangeSuccess" class="mb-3 text-sm text-emerald-700 dark:text-emerald-300">{{ emailChangeSuccess }}</p>
        <p v-if="linkError" class="mb-3 text-sm text-rose-700 dark:text-rose-300">{{ linkError }}</p>

        <div class="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden">

          <!-- GitHub -->
          <div class="flex items-center gap-4 px-4 py-3.5">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-slate-900">
              <svg class="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.477 2 2 6.477 2 12c0 4.418 2.865 8.166 6.839 9.489.5.092.682-.217.682-.483 0-.237-.009-.868-.013-1.703-2.782.604-3.369-1.342-3.369-1.342-.454-1.155-1.11-1.463-1.11-1.463-.908-.62.069-.607.069-.607 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.268 2.75 1.026A9.578 9.578 0 0112 6.836a9.59 9.59 0 012.504.337c1.909-1.294 2.747-1.026 2.747-1.026.546 1.377.203 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.579.688.481C19.138 20.163 22 16.418 22 12c0-5.523-4.477-10-10-10z"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">GitHub</p>
              <p class="text-xs text-slate-500 dark:text-slate-400">
                {{ linkedProviders.has('github') ? 'Connected. You can sign in with GitHub.' : 'Sign in with your GitHub account.' }}
              </p>
            </div>
            <button
              v-if="linkedProviders.has('github')"
              class="flex-shrink-0 rounded-full bg-rose-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              :disabled="unlinkingProvider === 'github'"
              @click="unlinkProvider('github')"
            >
              {{ unlinkingProvider === 'github' ? 'Disconnecting...' : 'Disconnect' }}
            </button>
            <button
              v-else
              class="flex-shrink-0 rounded-full bg-slate-900 px-4 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50"
              :disabled="linkingProvider !== null"
              @click="linkProvider('github')"
            >
              {{ linkingProvider === 'github' ? 'Redirecting...' : 'Connect' }}
            </button>
          </div>

          <!-- Google -->
          <div class="flex items-center gap-4 px-4 py-3.5">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-slate-900">
              <svg class="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor">
                <path d="M21.35 11.1H12v2.9h5.35c-.23 1.22-.94 2.25-2 2.95v2.45h3.24c1.9-1.75 3-4.33 3-7.3 0-.7-.07-1.37-.24-2z"/>
                <path d="M12 22c2.7 0 4.96-.9 6.62-2.43l-3.24-2.52c-.9.6-2.04.96-3.38.96-2.6 0-4.8-1.76-5.6-4.12H3.06v2.6C4.7 19.93 8.1 22 12 22z"/>
                <path d="M6.4 13.89A6.08 6.08 0 016.1 12c0-.66.12-1.3.3-1.89V7.51H3.06A10.02 10.02 0 002 12c0 1.6.38 3.12 1.06 4.49l3.34-2.6z"/>
                <path d="M12 5.88c1.47 0 2.79.5 3.83 1.5l2.87-2.87C16.96 2.9 14.7 2 12 2 8.1 2 4.7 4.07 3.06 7.51l3.34 2.6C7.2 7.64 9.4 5.88 12 5.88z"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Google</p>
              <p class="text-xs text-slate-500 dark:text-slate-400">
                {{ linkedProviders.has('google') ? 'Connected. You can sign in with Google.' : 'Sign in with your Google account.' }}
              </p>
            </div>
            <button
              v-if="linkedProviders.has('google')"
              class="flex-shrink-0 rounded-full bg-rose-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              :disabled="unlinkingProvider === 'google'"
              @click="unlinkProvider('google')"
            >
              {{ unlinkingProvider === 'google' ? 'Disconnecting...' : 'Disconnect' }}
            </button>
            <button
              v-else
              class="flex-shrink-0 rounded-full bg-slate-900 px-4 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50"
              :disabled="linkingProvider !== null"
              @click="linkProvider('google')"
            >
              {{ linkingProvider === 'google' ? 'Redirecting...' : 'Connect' }}
            </button>
          </div>

          <!-- Apple (coming soon) -->
          <div class="flex items-center gap-4 px-4 py-3.5 opacity-50">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-slate-900">
              <svg class="h-4 w-4 text-white" viewBox="0 0 24 24" fill="currentColor">
                <path d="M17.05 20.28c-.98.95-2.05.8-3.08.35-1.09-.46-2.09-.48-3.24 0-1.44.62-2.2.44-3.06-.35C2.79 15.25 3.51 7.7 9.05 7.4c1.39.07 2.35.74 3.15.8 1.2-.24 2.35-.93 3.64-.84 1.54.12 2.71.74 3.48 1.87-3.17 1.87-2.42 5.97.48 7.12-.57 1.5-1.32 2.99-2.75 3.93zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Apple</p>
              <p class="text-xs text-slate-500 dark:text-slate-400">Sign in with your Apple ID.</p>
            </div>
            <span class="flex-shrink-0 rounded-full bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400">Coming soon</span>
          </div>

          <!-- Email / OTP -->
          <div class="flex items-center gap-4 px-4 py-3.5">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-700 dark:bg-slate-800">
              <svg class="h-4 w-4 text-slate-700 dark:text-slate-200" viewBox="0 0 24 24" fill="none">
                <path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ userEmail }}</p>
              <p class="text-xs text-slate-500 dark:text-slate-400">You can sign in with OTP codes sent to your email.</p>
            </div>
            <button
              class="flex-shrink-0 rounded-full bg-slate-900 px-4 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 transition-colors"
              @click="showEmailChange = !showEmailChange"
            >
              Change Email
            </button>
          </div>

          <!-- Email change inline -->
          <div v-if="showEmailChange" class="bg-slate-50 dark:bg-slate-800/40 px-4 py-4">
            <div class="flex gap-2">
              <input
                v-model="newEmail"
                type="email"
                placeholder="new@example.com"
                class="flex-1 rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
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
      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="mb-1 text-base font-semibold text-slate-900 dark:text-slate-100">Two-Factor Authentication</h2>
        <p class="mb-4 text-sm text-slate-500 dark:text-slate-400">
          Only applies to magic link sign-in. Google/GitHub sign-in is already secured by that provider's own account.
        </p>

        <p
          v-if="hasNoSocialProvider && !mfaEnabled && mfaStep === 'idle'"
          class="mb-4 rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-300"
        >
          You sign in with email only, so enabling 2FA is a strong idea to protect your account.
        </p>
        <p v-if="mfaError" class="mb-3 text-sm text-rose-700 dark:text-rose-300">{{ mfaError }}</p>

        <!-- Idle: show current status -->
        <div v-if="mfaStep === 'idle'" class="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden">
          <div class="flex items-center gap-4 px-4 py-3.5">
            <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border border-slate-200 dark:border-slate-800 bg-white dark:border-slate-700 dark:bg-slate-800">
              <svg class="h-4 w-4 text-slate-700 dark:text-slate-200" viewBox="0 0 24 24" fill="none">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Authenticator App</p>
              <p class="text-xs text-slate-500 dark:text-slate-400">
                <template v-if="mfaEnabled">
                  Enabled.
                  <span v-if="backupCodesRemaining !== null">{{ backupCodesRemaining }} backup codes remaining.</span>
                </template>
                <template v-else>Add an extra layer of security when you sign in.</template>
              </p>
            </div>
            <button
              v-if="mfaEnabled"
              class="flex-shrink-0 rounded-full bg-rose-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              :disabled="mfaBusy"
              @click="disableMfa"
            >
              {{ mfaBusy ? 'Disabling...' : 'Disable' }}
            </button>
            <button
              v-else-if="hasNoSocialProvider"
              class="flex-shrink-0 rounded-full bg-slate-900 px-4 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50"
              :disabled="mfaBusy"
              @click="startMfaEnrollment"
            >
              {{ mfaBusy ? 'Starting...' : 'Enable' }}
            </button>
            <span
              v-else
              class="flex-shrink-0 rounded-full bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400"
              title="Disconnect Google/GitHub first. 2FA would also gate those sign-ins, since Supabase applies it account-wide."
            >
              Disconnect social login first
            </span>
          </div>
          <div v-if="mfaEnabled" class="flex items-center gap-4 px-4 py-3.5">
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Backup codes</p>
              <p class="text-xs text-slate-500 dark:text-slate-400">Generate a new set if you're running low or lost your old ones.</p>
            </div>
            <button
              class="flex-shrink-0 rounded-full border border-slate-200 dark:border-slate-800 px-4 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40 disabled:opacity-50"
              :disabled="mfaBusy"
              @click="regenerateBackupCodes"
            >
              Regenerate
            </button>
          </div>
        </div>

        <!-- Enrolling: QR code + verification -->
        <div v-else-if="mfaStep === 'enrolling'" class="rounded-xl border border-slate-200 dark:border-slate-800 p-5">
          <p class="mb-3 text-sm text-slate-700 dark:text-slate-200">
            Scan this QR code with your authenticator app (e.g. Google Authenticator, 1Password, Authy, Ente Auth).
          </p>
          <img
            v-if="mfaQrSvg"
            :src="mfaQrSvg"
            alt="2FA QR code"
            class="mb-3 h-40 w-40 rounded-lg border border-slate-200 dark:border-slate-800"
          />
          <p v-if="mfaSecret" class="mb-4 text-xs text-slate-500 dark:text-slate-400">
            Can't scan it? Enter this code manually: <span class="font-mono text-slate-800 dark:text-slate-100">{{ mfaSecret }}</span>
          </p>
          <label class="mb-3 block text-sm text-slate-700 dark:text-slate-200">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">6-digit code</span>
            <input
              v-model="mfaVerifyCode"
              type="text"
              inputmode="numeric"
              maxlength="6"
              placeholder="123456"
              class="w-full max-w-[160px] rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
              @keyup.enter="confirmMfaEnrollment"
            />
          </label>
          <div class="flex gap-3">
            <button
              class="rounded-lg border border-slate-200 dark:border-slate-800 px-4 py-2 text-sm font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800/40"
              @click="cancelMfaEnrollment"
            >
              Cancel
            </button>
            <button
              class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              :disabled="mfaBusy || mfaVerifyCode.trim().length < 6"
              @click="confirmMfaEnrollment"
            >
              {{ mfaBusy ? 'Verifying...' : 'Verify & enable' }}
            </button>
          </div>
        </div>

        <!-- Backup codes: shown once -->
        <div v-else-if="mfaStep === 'backup-codes'" class="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 p-5">
          <p class="mb-1 text-sm font-semibold text-amber-900 dark:text-amber-200">Save your backup codes</p>
          <p class="mb-4 text-sm text-amber-800 dark:text-amber-300">
            Each code can be used once to sign in if you lose access to your authenticator app. This is the only time
            they'll be shown, so store them somewhere safe (a password manager, or printed).
          </p>
          <div class="mb-4 grid grid-cols-2 gap-2 rounded-lg bg-white p-4 font-mono text-sm text-slate-800 dark:bg-slate-800 dark:text-slate-100">
            <span v-for="code in backupCodes" :key="code">{{ code }}</span>
          </div>
          <label class="mb-4 flex items-start gap-2 text-sm text-amber-900 dark:text-amber-200">
            <input v-model="backupCodesConfirmed" type="checkbox" class="mt-0.5" />
            <span>I've saved or printed these codes and stored them securely.</span>
          </label>
          <button
            class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            :disabled="!backupCodesConfirmed"
            @click="finishMfaSetup"
          >
            Done
          </button>
        </div>
      </section>

      <!-- Danger Zone -->
      <section class="rounded-2xl border border-rose-100 bg-white p-5 shadow-sm dark:border-rose-500/30 dark:bg-slate-900">
        <h2 class="mb-1 text-base font-semibold text-rose-700 dark:text-rose-300">Danger zone</h2>
        <p class="mb-4 text-sm text-slate-500 dark:text-slate-400">
          Irreversible actions. Deleting your account removes all publications, webhook configurations, and event history permanently.
        </p>
        <button
          class="rounded-lg border border-rose-200 dark:border-rose-500/30 px-4 py-2 text-sm font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50"
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
          <div class="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl dark:bg-slate-900">
            <h3 class="mb-2 text-base font-semibold text-slate-900 dark:text-slate-100">Delete account permanently?</h3>
            <p class="mb-4 text-sm text-slate-500 dark:text-slate-400">
              This will remove all your publications, integrations, webhook events, and product mappings. Your subscription will need to be cancelled separately.
            </p>
            <p class="mb-1 text-xs font-semibold text-slate-600 dark:text-slate-300">
              Type your email address to confirm:
              <span class="font-mono text-slate-800 dark:text-slate-100">{{ userEmail }}</span>
            </p>
            <input
              v-model="deleteConfirmInput"
              type="email"
              class="mb-4 w-full rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rose-300"
              placeholder="your@email.com"
            />
            <p v-if="deleteError" class="mb-3 text-sm text-rose-700 dark:text-rose-300">{{ deleteError }}</p>
            <div class="flex gap-3">
              <button
                class="flex-1 rounded-lg border border-slate-200 dark:border-slate-800 px-4 py-2 text-sm font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800/40"
                @click="showDeleteDialog = false"
              >
                Cancel
              </button>
              <button
                class="flex-1 rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-40"
                :disabled="!deleteConfirmMatch || deleting"
                @click="askForConfirmation"
              >
                {{ deleting ? 'Deleting...' : 'Delete my account' }}
              </button>
            </div>
          </div>
        </div>
      </Teleport>

      <StepUpDialog
        :open="showStepUp"
        purpose="delete_account"
        title="Confirm it is you"
        description="Deleting your account removes every publication, integration and event permanently. Confirm to continue."
        confirm-label="Delete my account"
        destructive
        @confirmed="performDelete"
        @close="showStepUp = false"
      />

    </div>
  </AppShell>
</template>

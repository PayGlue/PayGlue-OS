// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { supabase } from '../lib/supabase'
import { useSessionStore } from '../stores/session'
import { verifyMfaBackupCode } from '../lib/api'
import PayGlueLogo from '../components/PayGlueLogo.vue'

const router = useRouter()
const session = useSessionStore()

const useBackupCode = ref(false)
const code = ref('')
const error = ref<string | null>(null)
const verifying = ref(false)

const proceedToApp = async () => {
  await session.bootstrap()
  router.replace({ name: 'tenant-select' })
}

const verifyTotp = async () => {
  error.value = null
  verifying.value = true
  try {
    const { data: factors, error: factorsError } = await supabase.auth.mfa.listFactors()
    if (factorsError || !factors) throw factorsError ?? new Error('Could not load 2FA factors.')
    const totp = factors.totp.find((f) => f.status === 'verified')
    if (!totp) throw new Error('No 2FA method found on this account.')

    const { data: challenge, error: challengeError } = await supabase.auth.mfa.challenge({
      factorId: totp.id,
    })
    if (challengeError) throw challengeError

    const { error: verifyError } = await supabase.auth.mfa.verify({
      factorId: totp.id,
      challengeId: challenge.id,
      code: code.value.trim(),
    })
    if (verifyError) throw verifyError

    await proceedToApp()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Invalid code. Please try again.'
  } finally {
    verifying.value = false
  }
}

const verifyBackupCode = async () => {
  error.value = null
  verifying.value = true
  try {
    const { data: sessionData } = await supabase.auth.getSession()
    const idToken = sessionData.session?.access_token
    if (!idToken) throw new Error('Session expired, please sign in again.')

    const result = await verifyMfaBackupCode(idToken, code.value.trim())
    if (!result.valid) throw new Error('Invalid or already-used backup code.')

    await proceedToApp()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Invalid backup code.'
  } finally {
    verifying.value = false
  }
}

const submit = () => {
  if (!code.value.trim()) return
  if (useBackupCode.value) {
    verifyBackupCode()
  } else {
    verifyTotp()
  }
}

const signOut = async () => {
  await supabase.auth.signOut()
  session.clearSession()
  router.replace({ name: 'login' })
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center bg-white px-4">
    <div class="w-full max-w-sm">
      <div class="mb-8 flex justify-center">
        <PayGlueLogo size="lg" />
      </div>

      <h1 class="text-center text-2xl font-bold tracking-tight text-slate-900">Two-factor verification</h1>
      <p class="mt-2 text-center text-sm text-slate-500">
        {{ useBackupCode ? 'Enter one of your backup codes.' : 'Enter the 6-digit code from your authenticator app.' }}
      </p>

      <form class="mt-8 space-y-3" @submit.prevent="submit">
        <input
          v-model="code"
          type="text"
          :inputmode="useBackupCode ? 'text' : 'numeric'"
          :maxlength="useBackupCode ? 9 : 6"
          :placeholder="useBackupCode ? 'XXXX-XXXX' : '123456'"
          autofocus
          class="w-full rounded-xl border border-slate-300 px-4 py-3 text-center text-lg tracking-widest text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
        />
        <button
          type="submit"
          :disabled="verifying || !code.trim()"
          class="w-full rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {{ verifying ? 'Verifying...' : 'Verify' }}
        </button>
      </form>

      <p v-if="error" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</p>

      <button
        type="button"
        class="mt-4 w-full text-center text-sm font-semibold text-slate-500 hover:text-slate-700"
        @click="useBackupCode = !useBackupCode; code = ''; error = null"
      >
        {{ useBackupCode ? 'Use authenticator app instead' : 'Use a backup code instead' }}
      </button>

      <p class="mt-6 text-center text-sm text-slate-500">
        Not you?
        <button type="button" class="font-semibold text-slate-900 hover:underline" @click="signOut">Sign out</button>
      </p>
    </div>
  </main>
</template>

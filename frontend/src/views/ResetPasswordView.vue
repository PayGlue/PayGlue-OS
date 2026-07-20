// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import resetHeroImage from '../assets/reset-hero.jpg'
import PayGlueLogo from '../components/PayGlueLogo.vue'
import { supabase } from '../lib/supabase'

const route = useRoute()
const router = useRouter()

// Prefills the email and jumps straight to the code-entry step when arriving
// via the "open PayGlue" link in the reset-code email -- a plain deep link
// to this step, not a magic auto-login link, so it carries no token and
// can't hit the PKCE issues that got magic links removed here in the first
// place (PG-142).
const email = ref((route.query.email as string) || '')
const isSending = ref(false)
const sent = ref(Boolean(route.query.email))
const error = ref<string | null>(null)

// PG-142: 6-digit code entered here instead of the recovery link -- the
// link route (/auth/reset) only ever checked getSession() and relied on
// the SDK's automatic detectSessionInUrl to have already populated it,
// which we turned off in #117 (it raced against AuthCallbackView's own
// exchange). verifyOtp() establishes the session directly from the typed
// code, no link/redirect/PKCE exchange involved at all.
const otpDigits = ref(['', '', '', '', '', ''])
const otpInputs = ref<(HTMLInputElement | null)[]>([])
const verifying = ref(false)
const otpError = ref<string | null>(null)

const canSubmit = () => email.value.trim().includes('@')

const submit = async () => {
  if (!canSubmit()) return
  error.value = null
  isSending.value = true

  const { error: authError } = await supabase.auth.resetPasswordForEmail(
    email.value.trim(),
    { redirectTo: `${window.location.origin}/auth/callback` },
  )

  isSending.value = false
  if (authError) {
    console.error('[ResetPassword] Supabase error:', JSON.stringify(authError))
  }
  // Always show success -- never reveal whether an email exists in the system
  sent.value = true
}

const onDigitInput = (i: number, e: Event) => {
  const raw = (e.target as HTMLInputElement).value
  const val = raw.replace(/[^0-9]/g, '').slice(-1)
  otpDigits.value[i] = val
  if (val && i < 5) otpInputs.value[i + 1]?.focus()
}

const onDigitKeydown = (i: number, e: KeyboardEvent) => {
  if (e.key === 'Backspace' && !otpDigits.value[i] && i > 0) {
    otpInputs.value[i - 1]?.focus()
  }
}

const onDigitPaste = (e: ClipboardEvent) => {
  const text = e.clipboardData?.getData('text').replace(/[^0-9]/g, '') ?? ''
  if (text.length !== 6) return
  e.preventDefault()
  otpDigits.value = text.split('')
  otpInputs.value[5]?.focus()
}

const verifyCode = async () => {
  const token = otpDigits.value.join('')
  if (token.length !== 6) return
  otpError.value = null
  verifying.value = true
  const { data, error: authError } = await supabase.auth.verifyOtp({
    email: email.value.trim(),
    token,
    type: 'recovery',
  })
  if (authError || !data.session) {
    verifying.value = false
    otpError.value = authError?.message || 'That code is invalid or expired. Please try again.'
    otpDigits.value = ['', '', '', '', '', '']
    otpInputs.value[0]?.focus()
    return
  }
  // Stay disabled (verifying=true) through the navigation below -- codes are
  // single-use, so a stray second click here would resubmit an already-
  // consumed token and show a scary "expired" error over a real success.
  router.replace({ name: 'auth-reset' })
}
</script>

<template>
  <main class="min-h-screen bg-white antialiased">
    <div class="grid min-h-screen md:grid-cols-2">

      <!-- Form side -->
      <section class="flex flex-col items-center justify-center px-6 pt-12 pb-12">
        <div class="w-full max-w-sm">

          <div class="mb-8">
            <RouterLink to="/"><PayGlueLogo size="lg" /></RouterLink>
          </div>

          <h1 class="text-3xl font-bold tracking-tight text-slate-900">Reset password</h1>
          <p v-if="!sent" class="mt-2 text-sm text-slate-500">
            Enter your email and we'll send you a reset code.
          </p>

          <form v-if="!sent" class="mt-8 space-y-3" @submit.prevent="submit">
            <input
              v-model="email"
              type="email"
              placeholder="Email address"
              autocomplete="email"
              class="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />
            <button
              type="submit"
              :disabled="!canSubmit() || isSending"
              class="w-full rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {{ isSending ? 'Sending...' : 'Send reset code' }}
            </button>
          </form>

          <div v-else class="mt-8">
            <p class="text-sm text-slate-500">
              If <strong class="text-slate-900">{{ email }}</strong> has a PayGlue account, we sent a verification code. Enter the 6-digit code below.
            </p>
            <div class="mt-4 flex justify-between gap-2" @paste="onDigitPaste">
              <input
                v-for="i in 6"
                :key="i - 1"
                :ref="(el) => { otpInputs[i - 1] = el as HTMLInputElement }"
                v-model="otpDigits[i - 1]"
                type="text"
                inputmode="numeric"
                maxlength="1"
                autocomplete="one-time-code"
                class="h-14 w-12 rounded-xl border border-slate-300 text-center text-lg font-semibold text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                @input="onDigitInput(i - 1, $event)"
                @keydown="onDigitKeydown(i - 1, $event)"
              />
            </div>
            <button
              type="button"
              :disabled="verifying || otpDigits.join('').length !== 6"
              class="mt-4 w-full rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
              @click="verifyCode"
            >
              {{ verifying ? 'Verifying...' : 'Continue' }}
            </button>
            <p v-if="otpError" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ otpError }}</p>
          </div>

          <p v-if="error" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</p>

          <p class="mt-8 text-center text-sm text-slate-500">
            Remember your password?
            <RouterLink to="/login" class="font-semibold text-slate-900 hover:underline">Sign in</RouterLink>
          </p>
        </div>
      </section>

      <!-- Hero image side -->
      <aside
        class="relative hidden min-h-screen border-l border-slate-200 bg-cover bg-center md:block"
        :style="{ backgroundImage: `linear-gradient(rgba(12,18,36,0.18), rgba(12,18,36,0.18)), url(${resetHeroImage})` }"
        aria-hidden="true"
      >
        <p class="absolute bottom-3 right-3 rounded-lg bg-black/50 px-2 py-1 text-[10px] text-white/80">
          Photo by <a href="https://unsplash.com/@ujesh" target="_blank" rel="noopener" class="underline">Ujesh Krishnan</a> on Unsplash
        </p>
      </aside>

    </div>
  </main>
</template>

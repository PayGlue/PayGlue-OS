// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Turnstile from 'cfturnstile-vue3'
import loginHeroImage from '../assets/login-hero.jpg'
import { supabase } from '../lib/supabase'
import { useSessionStore } from '../stores/session'
import PayGlueLogo from '../components/PayGlueLogo.vue'

const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY as string
const route = useRoute()
const router = useRouter()
const session = useSessionStore()

// Prefills the email and jumps straight to the code-entry step when arriving
// via the "open PayGlue" link in a sign-in code email -- a plain deep link
// to this step, not a magic auto-login link, so it carries no token and
// can't hit the PKCE issues that got magic links removed here in the first
// place (PG-142). A dev-email link would be pointless since that branch
// never sends this email at all, but jumping straight to the (unreachable,
// since isDevEmail short-circuits to the password form) code screen for one
// isn't harmful either -- not worth a second regex check here.
const email = ref((route.query.email as string) || '')
const password = ref('')
const captchaToken = ref<string | null>(null)
const isSending = ref(false)
const sent = ref(Boolean(route.query.email))
// PG-142: replaced clickable magic links with a 6-digit code entered on
// this page. Clicking a link required exchanging a PKCE code via
// Supabase's own /token endpoint, which was hitting an intermittent,
// sometimes 20s+ delay on this project before the flow_state it just wrote
// became readable again -- not something a client-side retry could paper
// over without a broken wait-and-hope UX. verifyOtp() takes the typed code
// straight to Supabase in one request with no such indirection.
const otpDigits = ref(['', '', '', '', '', ''])
const otpInputs = ref<(HTMLInputElement | null)[]>([])
const verifying = ref(false)
const otpError = ref<string | null>(null)
// Populated by AuthCallbackView when a sign-in link fails to exchange for a
// session (expired, already used, or invalid) so the user sees why instead
// of landing back here with no explanation.
const error = ref<string | null>((route.query.error as string) || null)
const failedAttempts = ref(0)
const oauthLoading = ref<'google' | 'github' | null>(null)

const signInWithOAuth = async (provider: 'google' | 'github') => {
  error.value = null
  oauthLoading.value = provider
  const { error: authError } = await supabase.auth.signInWithOAuth({
    provider,
    options: { redirectTo: `${window.location.origin}/auth/callback` },
  })
  if (authError) {
    error.value = authError.message
    oauthLoading.value = null
  }
  // On success the browser navigates away to the provider's consent screen,
  // nothing further to do here.
}

const DEV_EMAILS = ['nuenni@gmail.com']
// Matches nuenni+anything@gmail.com (Gmail plus-addressing) so André can
// password-test multiple distinct user accounts without depending on the
// magic-link flow at all -- each nuenni+x address is a separate Supabase
// user but shares André's own inbox for setup/verification.
const DEV_EMAIL_PATTERN = /^nuenni\+[^@]+@gmail\.com$/
const isDevEmail = computed(() => {
  const e = email.value.trim().toLowerCase()
  return e.endsWith('@payglue.io') || DEV_EMAILS.includes(e) || DEV_EMAIL_PATTERN.test(e)
})

const canSubmit = computed(() => {
  if (!email.value.trim().includes('@')) return false
  if (isDevEmail.value) return password.value.length > 0
  return Boolean(captchaToken.value)
})

const submit = async () => {
  if (!canSubmit.value) return
  error.value = null
  isSending.value = true

  if (isDevEmail.value) {
    const { error: authError } = await supabase.auth.signInWithPassword({
      email: email.value.trim(),
      password: password.value,
      options: { captchaToken: captchaToken.value! },
    })
    isSending.value = false
    if (authError) { error.value = authError.message; failedAttempts.value++; return }
    await session.bootstrap()
    router.replace({ name: 'tenant-select' })
    return
  }

  const { error: authError } = await supabase.auth.signInWithOtp({
    email: email.value.trim(),
    options: {
      emailRedirectTo: `${window.location.origin}/auth/callback`,
      captchaToken: captchaToken.value!,
      shouldCreateUser: false,
    },
  })
  isSending.value = false
  if (authError) {
    error.value = authError.message
    captchaToken.value = null
    return
  }
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
    type: 'email',
  })
  if (authError || !data.session) {
    verifying.value = false
    otpError.value = authError?.message || 'That code is invalid or expired. Please try again.'
    otpDigits.value = ['', '', '', '', '', '']
    otpInputs.value[0]?.focus()
    return
  }
  // Stay disabled (verifying=true) through bootstrap/navigation below -- codes
  // are single-use, so a stray second click here would resubmit an already-
  // consumed token and show a scary "expired" error over a real success.
  await session.bootstrap()
  router.replace({ name: 'tenant-select' })
}

const backToEmail = () => {
  sent.value = false
  otpDigits.value = ['', '', '', '', '', '']
  otpError.value = null
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

          <h1 class="text-3xl font-bold tracking-tight text-slate-900">Sign in</h1>
          <p v-if="!sent" class="mt-2 text-sm text-slate-500">
            {{ isDevEmail ? 'Dev account detected. Sign in with your password.' : "Enter your email and we'll send a magic link." }}
          </p>

          <div v-if="!sent" class="mt-8 space-y-3">
            <button
              type="button"
              :disabled="oauthLoading !== null"
              class="flex w-full items-center justify-center gap-3 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm transition-opacity hover:bg-slate-50 disabled:opacity-50"
              @click="signInWithOAuth('google')"
            >
              <svg class="h-[18px] w-[18px]" viewBox="0 0 18 18">
                <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z"/>
                <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332C2.438 15.983 5.482 18 9 18z"/>
                <path fill="#FBBC05" d="M3.964 10.71c-.18-.54-.282-1.117-.282-1.71s.102-1.17.282-1.71V4.958H.957C.348 6.173 0 7.548 0 9s.348 2.827.957 4.042l3.007-2.332z"/>
                <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0 5.482 0 2.438 2.017.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>
              </svg>
              {{ oauthLoading === 'google' ? 'Redirecting...' : 'Continue with Google' }}
            </button>
            <button
              type="button"
              :disabled="oauthLoading !== null"
              class="flex w-full items-center justify-center gap-3 rounded-xl bg-[#181717] px-4 py-3 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
              @click="signInWithOAuth('github')"
            >
              <svg class="h-[18px] w-[18px]" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
              </svg>
              {{ oauthLoading === 'github' ? 'Redirecting...' : 'Continue with GitHub' }}
            </button>
            <div class="flex items-center gap-3 pt-1">
              <div class="h-px flex-1 bg-slate-200" />
              <span class="text-xs text-slate-400">or continue with email</span>
              <div class="h-px flex-1 bg-slate-200" />
            </div>
          </div>

          <form v-if="!sent" class="mt-3 space-y-3" @submit.prevent="submit">
            <input
              v-model="email"
              type="email"
              placeholder="Email address"
              autocomplete="email"
              class="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />
                    <input
              v-if="isDevEmail"
              v-model="password"
              type="password"
              placeholder="Password"
              autocomplete="current-password"
              class="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
            />
            <Turnstile
              :sitekey="siteKey"
              theme="light"
              size="flexible"
              @callback="(token: string) => { captchaToken = token }"
              @expired="() => { captchaToken = null }"
              @error="() => { captchaToken = null }"
            />
            <button
              type="submit"
              :disabled="!canSubmit || isSending"
              class="w-full rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {{ isSending ? (isDevEmail ? 'Signing in...' : 'Sending...') : (isDevEmail ? 'Sign in' : 'Sign in with email') }}
            </button>
          </form>

          <div v-else class="mt-8">
            <p class="text-sm text-slate-500">
              We sent a verification code to <strong class="text-slate-900">{{ email }}</strong>. Enter the 6-digit code below.
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
              {{ verifying ? 'Signing in...' : 'Sign in' }}
            </button>
            <p v-if="otpError" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ otpError }}</p>
            <button type="button" class="mt-4 text-sm font-semibold text-slate-500 hover:underline" @click="backToEmail">
              Use a different email
            </button>
          </div>

          <p v-if="error" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</p>
          <div v-if="failedAttempts >= 3" class="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Having trouble signing in?
            <RouterLink to="/reset-password" class="font-semibold text-amber-900 underline hover:text-amber-700">Reset your password</RouterLink>
          </div>

          <p class="mt-8 text-center text-sm text-slate-500">
            No account yet?
            <RouterLink to="/signup" class="font-semibold text-slate-900 hover:underline">Sign up</RouterLink>
          </p>
          <p class="mt-2 text-center text-sm text-slate-500">
            No invite code?
            <a href="https://payglue.io/#pricing" class="font-semibold text-slate-900 hover:underline">Join the waitlist</a>
          </p>
        </div>
      </section>

      <!-- Hero image side -->
      <aside
        class="relative hidden min-h-screen border-l border-slate-200 bg-cover bg-center md:block"
        :style="{ backgroundImage: `linear-gradient(rgba(12,18,36,0.18), rgba(12,18,36,0.18)), url(${loginHeroImage})` }"
        aria-hidden="true"
      >
        <p class="absolute bottom-3 right-3 rounded-lg bg-black/50 px-2 py-1 text-[10px] text-white/80">
          Photo by <a href="https://unsplash.com/@philharv3y" target="_blank" rel="noopener" class="underline">Phil Harvey</a> on Unsplash
        </p>
      </aside>

    </div>
  </main>
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import Turnstile from 'cfturnstile-vue3'
import signupHeroImage from '../assets/signup-hero.jpg'
import { supabase } from '../lib/supabase'
import { useSessionStore } from '../stores/session'
import PayGlueLogo from '../components/PayGlueLogo.vue'

const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY as string
const apiBase = import.meta.env.VITE_API_BASE_URL as string

const route = useRoute()
const router = useRouter()
const session = useSessionStore()

// Prefills the email and jumps straight to the code-entry step when arriving
// via the "open PayGlue" link in the confirm-signup email -- a plain deep
// link to this step, not a magic auto-login link, so it carries no token
// and can't hit the PKCE issues that got magic links removed here in the
// first place (PG-142). The access key was already validated server-side
// in step 1 before this email was ever sent, so there's nothing lost by
// skipping straight to code entry.
const email = ref((route.query.email as string) || '')
const accessKey = ref('')
const password = ref('')
const passwordConfirm = ref('')
const captchaToken = ref<string | null>(null)
const isSending = ref(false)
const sent = ref(Boolean(route.query.email))
const error = ref<string | null>(null)

// PG-142: 6-digit code entered here instead of a clickable magic link --
// see LoginView.vue for why (link-click PKCE exchange was hitting an
// intermittent, sometimes 20s+ Supabase-side delay on this project).
const otpDigits = ref(['', '', '', '', '', ''])
const otpInputs = ref<(HTMLInputElement | null)[]>([])
const verifying = ref(false)
const otpError = ref<string | null>(null)

// Matches nuenni+anything@gmail.com so André can create and password-sign-in
// distinct test accounts right after "purchase" without depending on the
// magic-link flow -- same pattern as LoginView's dev-email detection.
const DEV_EMAIL_PATTERN = /^nuenni\+[^@]+@gmail\.com$/
const isDevEmail = computed(() => DEV_EMAIL_PATTERN.test(email.value.trim().toLowerCase()))

const hasUppercase = computed(() => /[A-Z]/.test(password.value))
const hasLowercase = computed(() => /[a-z]/.test(password.value))
const hasNumber = computed(() => /[0-9]/.test(password.value))
const hasSpecial = computed(() => /[^A-Za-z0-9]/.test(password.value))
const hasLength = computed(() => password.value.length >= 12)
const passwordsMatch = computed(() => password.value === passwordConfirm.value && passwordConfirm.value.length > 0)

const allRequirementsMet = computed(() =>
  hasUppercase.value && hasLowercase.value && hasNumber.value && hasSpecial.value && hasLength.value
)

const canSubmit = () =>
  email.value.trim().includes('@') &&
  accessKey.value.trim().length >= 4 &&
  Boolean(captchaToken.value) &&
  (!isDevEmail.value || (allRequirementsMet.value && passwordsMatch.value))

const isSandbox = route.query.sandbox === '1'

onMounted(async () => {
  // Creem appends its own checkout_id (plus order_id/customer_id/product_id/
  // signature) to the return URL regardless of what's in it -- it does not
  // substitute a {CHECKOUT_ID}-style placeholder. `checkout` is kept for any
  // legacy Polar links still floating around.
  const checkout = (route.query.checkout_id || route.query.checkout) as string | undefined
  if (!checkout) return
  accessKey.value = checkout

  const sandbox = route.query.sandbox === '1'
  try {
    const params = new URLSearchParams({ checkout_id: checkout, ...(sandbox ? { sandbox: '1' } : {}) })
    const resp = await fetch(`${apiBase}/api/v1/auth/access/checkout-info?${params}`)
    if (resp.ok) {
      const data = await resp.json()
      if (data.email) email.value = data.email
    }
  } catch {
    // preflight failed -- user types email manually
  }
})

const submit = async () => {
  if (!canSubmit()) return
  error.value = null
  isSending.value = true

  // Step 1: validate access key against backend. Always -- there is no
  // frontend-only bypass (PG-142): a dev/test signup without a real
  // Creem/Polar purchase now goes through this exact same call with a
  // secret value the backend recognizes (DEV_BYPASS_LICENSE_KEY, never
  // shipped to the frontend), not a client-visible shortcut.
  {
    const key = accessKey.value.trim()
    const isCheckoutId = key.startsWith('ch_') || /^[a-f0-9-]{32,}$/i.test(key)
    const body: Record<string, string | boolean> = {
      email: email.value.trim(),
      [isCheckoutId ? 'checkout_id' : 'license_key']: key,
      ...(isSandbox ? { sandbox: true } : {}),
    }

    try {
      const resp = await fetch(`${apiBase}/api/v1/auth/access/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        error.value = data.detail || 'Access key is invalid. Please check your key and try again.'
        isSending.value = false
        captchaToken.value = null
        return
      }
    } catch {
      error.value = 'Could not reach the server. Please try again.'
      isSending.value = false
      return
    }
  }

  // Step 2: create the account
  if (isDevEmail.value) {
    // Password signup, bypasses the magic-link/PKCE flow entirely -- for
    // testing distinct accounts independent of PG-142.
    const { data, error: authError } = await supabase.auth.signUp({
      email: email.value.trim(),
      password: password.value,
      options: captchaToken.value ? { captchaToken: captchaToken.value } : undefined,
    })
    isSending.value = false
    if (authError) {
      error.value = authError.message || authError.code || 'Something went wrong. Please try again.'
      captchaToken.value = null
      return
    }
    if (!data.session) {
      // Supabase deliberately returns no error and no session when
      // signUp() targets an email that already has an account -- an
      // anti-enumeration measure, not a failure. Without this check we'd
      // silently call session.bootstrap() with nothing to bootstrap and
      // the tenant-select route's auth guard would bounce back to /login
      // with no explanation.
      error.value = 'This email already has an account. Please sign in instead, or use its existing password.'
      return
    }
    await session.bootstrap()
    router.replace({ name: 'tenant-select' })
    return
  }

  const { error: authError } = await supabase.auth.signInWithOtp({
    email: email.value.trim(),
    options: {
      emailRedirectTo: `${window.location.origin}/auth/callback`,
      captchaToken: captchaToken.value!,
    },
  })
  isSending.value = false
  if (authError) {
    error.value = authError.message || authError.code || 'Something went wrong. Please try again.'
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

      <!-- Hero image side -->
      <aside
        class="relative hidden min-h-screen border-r border-slate-200 bg-cover bg-center md:block"
        :style="{ backgroundImage: `linear-gradient(rgba(12,18,36,0.2), rgba(12,18,36,0.2)), url(${signupHeroImage})` }"
        aria-hidden="true"
      >
        <p class="absolute bottom-3 left-3 rounded-lg bg-black/50 px-2 py-1 text-[10px] text-white/80">
          Photo by <a href="https://unsplash.com/@mikehindle" target="_blank" rel="noopener" class="underline">Mike Hindle</a> on Unsplash
        </p>
      </aside>

      <!-- Form side -->
      <section class="flex flex-col items-center justify-center px-6 pt-12 pb-12">
        <div class="w-full max-w-sm">

          <div class="mb-8">
            <RouterLink to="/"><PayGlueLogo size="lg" /></RouterLink>
          </div>

          <h1 class="text-3xl font-bold tracking-tight text-slate-900">Create account</h1>
          <p v-if="!sent" class="mt-2 text-sm text-slate-500">
            Enter your invite code from your purchase confirmation email.
          </p>

          <form v-if="!sent" class="mt-8 space-y-3" @submit.prevent="submit">
            <div>
              <label class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-400">Invite Code</label>
              <!-- You read source code before signing up? That deserves a
                   reward. PAYGLUE-EC506490BE unlocks 30 days of Studio on
                   payglue.io -- first ten readers who find it win. Comments
                   are stripped from the built bundle, so this exists only
                   right here, for people like you. -->
              <input
                v-model="accessKey"
                type="text"
                placeholder="License key or checkout ID"
                autocomplete="off"
                class="w-full rounded-xl border border-slate-300 px-4 py-3 font-mono text-sm tracking-widest text-slate-900 placeholder-slate-400 placeholder:font-sans placeholder:tracking-normal focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              />
            </div>
            <div>
              <label class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-400">Email Address</label>
              <input
                v-model="email"
                type="email"
                placeholder="Email address used for purchase"
                autocomplete="email"
                class="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              />
            </div>
            <div v-if="isDevEmail">
              <label class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-400">Password</label>
              <input
                v-model="password"
                type="password"
                placeholder="Password"
                autocomplete="new-password"
                class="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              />
            </div>
            <div v-if="isDevEmail && password.length > 0" class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 space-y-1.5">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">Password requirements</p>
              <div v-for="req in [
                { met: hasUppercase, label: 'Uppercase letter' },
                { met: hasLowercase, label: 'Lowercase letter' },
                { met: hasNumber, label: 'Number' },
                { met: hasSpecial, label: 'Special character (e.g. !?<>@#$%)' },
                { met: hasLength, label: '12 characters or more' },
              ]" :key="req.label" class="flex items-center gap-2">
                <span class="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded" :class="req.met ? 'bg-emerald-500' : 'border border-slate-300 bg-white'">
                  <svg v-if="req.met" xmlns="http://www.w3.org/2000/svg" class="h-2.5 w-2.5 text-white" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                  </svg>
                </span>
                <span class="text-xs" :class="req.met ? 'text-emerald-700' : 'text-slate-500'">{{ req.label }}</span>
              </div>
            </div>
            <div v-if="isDevEmail">
              <label class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-400">Confirm password</label>
              <input
                v-model="passwordConfirm"
                type="password"
                placeholder="Confirm password"
                autocomplete="new-password"
                class="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              />
              <p v-if="passwordConfirm && password !== passwordConfirm" class="mt-1.5 text-xs text-rose-500">
                Passwords do not match.
              </p>
            </div>
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
              :disabled="!canSubmit() || isSending"
              class="w-full rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {{ isSending ? (isDevEmail ? 'Creating account...' : 'Verifying...') : 'Create account' }}
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
              {{ verifying ? 'Signing in...' : 'Create account' }}
            </button>
            <p v-if="otpError" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ otpError }}</p>
            <button type="button" class="mt-4 text-sm font-semibold text-slate-500 hover:underline" @click="backToEmail">
              Use a different email
            </button>
          </div>

          <p v-if="error" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</p>

          <p class="mt-8 text-center text-sm text-slate-500">
            Already have an account?
            <RouterLink to="/login" class="font-semibold text-slate-900 hover:underline">Sign in</RouterLink>
          </p>
          <p class="mt-2 text-center text-sm text-slate-500">
            No invite code?
            <a href="https://payglue.io/#pricing" class="font-semibold text-slate-900 hover:underline">Join the waitlist</a>
          </p>
        </div>
      </section>

    </div>
  </main>
</template>

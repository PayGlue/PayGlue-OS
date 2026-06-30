// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import Turnstile from 'cfturnstile-vue3'
import signupHeroImage from '../assets/signup-hero.jpg'
import { supabase } from '../lib/supabase'
import PayGlueLogo from '../components/PayGlueLogo.vue'

const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY as string
const apiBase = import.meta.env.VITE_API_BASE_URL as string

const route = useRoute()

const email = ref('')
const accessKey = ref('')
const captchaToken = ref<string | null>(null)
const isSending = ref(false)
const sent = ref(false)
const error = ref<string | null>(null)

// Dev bypass — never hits the backend
const DEV_CODES = ['dev']
const isDevCode = () => DEV_CODES.includes(accessKey.value.trim().toLowerCase())

const canSubmit = () =>
  email.value.trim().includes('@') &&
  accessKey.value.trim().length >= 4 &&
  (isDevCode() || Boolean(captchaToken.value))

const isSandbox = route.query.sandbox === '1'

onMounted(async () => {
  const checkout = route.query.checkout as string | undefined
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
    // preflight failed — user types email manually
  }
})

const submit = async () => {
  if (!canSubmit()) return
  error.value = null
  isSending.value = true

  // Step 1: validate access key against backend (skip for dev code)
  if (!isDevCode()) {
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

  // Step 2: send magic link via Supabase
  const otpOptions: Parameters<typeof supabase.auth.signInWithOtp>[0] = {
    email: email.value.trim(),
    options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
  }
  if (!isDevCode() && captchaToken.value) {
    otpOptions.options!.captchaToken = captchaToken.value
  }

  const { error: authError } = await supabase.auth.signInWithOtp(otpOptions)
  isSending.value = false
  if (authError) {
    error.value = authError.message || authError.code || 'Something went wrong. Please try again.'
    captchaToken.value = null
    return
  }
  sent.value = true
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
          <p class="mt-2 text-sm text-slate-500">
            Enter your invite code from your purchase confirmation email.
          </p>

          <form v-if="!sent" class="mt-8 space-y-3" @submit.prevent="submit">
            <div>
              <label class="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-400">Invite Code</label>
              <input
                v-model="accessKey"
                type="text"
                placeholder="PAYGLUE-XXXX-XXXX or checkout ID"
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
            <Turnstile
              v-if="!isDevCode()"
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
              {{ isSending ? 'Verifying...' : 'Create account' }}
            </button>
          </form>

          <div v-else class="mt-8 rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4">
            <p class="text-sm font-semibold text-emerald-800">Check your inbox</p>
            <p class="mt-1 text-sm text-emerald-700">
              We sent a magic link to <strong>{{ email }}</strong>. Click it to complete your account.
            </p>
          </div>

          <p v-if="error" class="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</p>

          <p class="mt-8 text-center text-sm text-slate-500">
            Already have an account?
            <RouterLink to="/login" class="font-semibold text-slate-900 hover:underline">Sign in</RouterLink>
          </p>
          <p class="mt-2 text-center text-sm text-slate-500">
            No invite code?
            <a href="https://payglue.io/#stay-informed" class="font-semibold text-slate-900 hover:underline">Join the waitlist</a>
          </p>
        </div>
      </section>

    </div>
  </main>
</template>

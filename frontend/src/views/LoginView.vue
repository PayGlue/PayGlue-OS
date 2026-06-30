// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Turnstile from 'cfturnstile-vue3'
import loginHeroImage from '../assets/login-hero.jpg'
import { supabase } from '../lib/supabase'
import { useSessionStore } from '../stores/session'
import PayGlueLogo from '../components/PayGlueLogo.vue'

const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY as string
const router = useRouter()
const session = useSessionStore()

const email = ref('')
const password = ref('')
const captchaToken = ref<string | null>(null)
const isSending = ref(false)
const sent = ref(false)
const error = ref<string | null>(null)
const failedAttempts = ref(0)

const DEV_EMAILS = ['nuenni@gmail.com']
const isDevEmail = computed(() => {
  const e = email.value.trim().toLowerCase()
  return e.endsWith('@payglue.io') || DEV_EMAILS.includes(e)
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
          <p class="mt-2 text-sm text-slate-500">
            {{ isDevEmail ? 'Dev account detected. Sign in with your password.' : "Enter your email and we'll send a magic link." }}
          </p>

          <form v-if="!sent" class="mt-8 space-y-3" @submit.prevent="submit">
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
              {{ isSending ? (isDevEmail ? 'Signing in...' : 'Sending...') : (isDevEmail ? 'Sign in' : 'Send magic link') }}
            </button>
          </form>

          <div v-else class="mt-8 rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4">
            <p class="text-sm font-semibold text-emerald-800">Check your inbox</p>
            <p class="mt-1 text-sm text-emerald-700">If <strong>{{ email }}</strong> has a PayGlue account, a magic link is on its way. Click it to sign in.</p>
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
            <a href="https://payglue.io/#stay-informed" class="font-semibold text-slate-900 hover:underline">Join the waitlist</a>
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

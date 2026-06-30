// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import resetHeroImage from '../assets/reset-hero.jpg'
import PayGlueLogo from '../components/PayGlueLogo.vue'
import { supabase } from '../lib/supabase'

const email = ref('')
const isSending = ref(false)
const sent = ref(false)
const error = ref<string | null>(null)

const canSubmit = () => email.value.trim().includes('@')

const submit = async () => {
  if (!canSubmit()) return
  error.value = null
  isSending.value = true

  const { error: authError } = await supabase.auth.resetPasswordForEmail(
    email.value.trim(),
    { redirectTo: `${window.location.origin}/auth/reset` },
  )

  isSending.value = false
  if (authError) {
    console.error('[ResetPassword] Supabase error:', JSON.stringify(authError))
  }
  // Always show success — never reveal whether an email exists in the system
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

          <h1 class="text-3xl font-bold tracking-tight text-slate-900">Reset password</h1>
          <p class="mt-2 text-sm text-slate-500">
            Enter your email and we'll send you a reset link.
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
              {{ isSending ? 'Sending...' : 'Send reset link' }}
            </button>
          </form>

          <div v-else class="mt-8 rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4">
            <p class="text-sm font-semibold text-emerald-800">Check your inbox</p>
            <p class="mt-1 text-sm text-emerald-700">
              If <strong>{{ email }}</strong> has a PayGlue account, a reset link is on its way. Click it to choose a new password.
            </p>
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

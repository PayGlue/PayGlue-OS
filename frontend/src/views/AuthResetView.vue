// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import resetNewHeroImage from '../assets/reset-new-hero.jpg'
import PayGlueLogo from '../components/PayGlueLogo.vue'
import { supabase } from '../lib/supabase'

const router = useRouter()

const password = ref('')
const passwordConfirm = ref('')
const showPassword = ref(false)
const showConfirm = ref(false)
const isSaving = ref(false)
const saved = ref(false)
const error = ref<string | null>(null)
const sessionReady = ref(false)

onMounted(async () => {
  const { data } = await supabase.auth.getSession()
  if (data.session) {
    sessionReady.value = true
  } else {
    error.value = 'This reset link is invalid or has expired. Please request a new one.'
  }
})

const hasUppercase = computed(() => /[A-Z]/.test(password.value))
const hasLowercase = computed(() => /[a-z]/.test(password.value))
const hasNumber = computed(() => /[0-9]/.test(password.value))
const hasSpecial = computed(() => /[^A-Za-z0-9]/.test(password.value))
const hasLength = computed(() => password.value.length >= 12)
const passwordsMatch = computed(() => password.value === passwordConfirm.value && passwordConfirm.value.length > 0)

const allRequirementsMet = computed(() =>
  hasUppercase.value && hasLowercase.value && hasNumber.value && hasSpecial.value && hasLength.value
)

const canSubmit = computed(() =>
  allRequirementsMet.value && passwordsMatch.value
)

const submit = async () => {
  if (!canSubmit.value) return
  error.value = null
  isSaving.value = true

  const { error: authError } = await supabase.auth.updateUser({ password: password.value })
  isSaving.value = false

  if (authError) {
    error.value = authError.message || 'Something went wrong. Please try again.'
    return
  }
  saved.value = true
  setTimeout(() => router.push('/login'), 2500)
}
</script>

<template>
  <main class="min-h-screen bg-white antialiased">
    <div class="grid min-h-screen md:grid-cols-2">

      <!-- Hero image side -->
      <aside
        class="relative hidden min-h-screen border-r border-slate-200 bg-cover bg-center md:block"
        :style="{ backgroundImage: `linear-gradient(rgba(12,18,36,0.18), rgba(12,18,36,0.18)), url(${resetNewHeroImage})` }"
        aria-hidden="true"
      >
        <p class="absolute bottom-3 left-3 rounded-lg bg-black/50 px-2 py-1 text-[10px] text-white/80">
          Photo by <a href="https://unsplash.com/@mahdi17" target="_blank" rel="noopener" class="underline">Md Mahdi</a> on Unsplash
        </p>
      </aside>

      <!-- Form side -->
      <section class="flex flex-col items-center justify-center px-6 pt-12 pb-12">
        <div class="w-full max-w-sm">

          <div class="mb-8">
            <RouterLink to="/"><PayGlueLogo size="lg" /></RouterLink>
          </div>

          <h1 class="text-3xl font-bold tracking-tight text-slate-900">New password</h1>
          <p class="mt-2 text-sm text-slate-500">
            Choose a new password for your account.
          </p>

          <form v-if="!saved && sessionReady" class="mt-8 space-y-3" @submit.prevent="submit">
            <!-- Password field -->
            <div class="relative">
              <input
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="New password"
                autocomplete="new-password"
                class="w-full rounded-xl border border-slate-300 px-4 py-3 pr-11 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              />
              <button
                type="button"
                class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                @click="showPassword = !showPassword"
                :aria-label="showPassword ? 'Hide password' : 'Show password'"
              >
                <svg v-if="showPassword" xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              </button>
            </div>

            <!-- Requirements checklist -->
            <div v-if="password.length > 0" class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 space-y-1.5">
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

            <!-- Confirm password field -->
            <div class="relative">
              <input
                v-model="passwordConfirm"
                :type="showConfirm ? 'text' : 'password'"
                placeholder="Confirm new password"
                autocomplete="new-password"
                class="w-full rounded-xl border border-slate-300 px-4 py-3 pr-11 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              />
              <button
                type="button"
                class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                @click="showConfirm = !showConfirm"
                :aria-label="showConfirm ? 'Hide password' : 'Show password'"
              >
                <svg v-if="showConfirm" xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              </button>
            </div>
            <p v-if="passwordConfirm && !passwordsMatch" class="text-xs text-rose-500">
              Passwords do not match.
            </p>

            <button
              type="submit"
              :disabled="!canSubmit || isSaving"
              class="w-full rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {{ isSaving ? 'Saving...' : 'Set new password' }}
            </button>
          </form>

          <div v-if="saved" class="mt-8 rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4">
            <p class="text-sm font-semibold text-emerald-800">Password updated</p>
            <p class="mt-1 text-sm text-emerald-700">Redirecting you to sign in...</p>
          </div>

          <p v-if="error" class="mt-8 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {{ error }}
            <RouterLink v-if="!sessionReady" to="/reset-password" class="mt-2 block font-semibold text-rose-800 hover:underline">Request a new link</RouterLink>
          </p>

        </div>
      </section>

    </div>
  </main>
</template>

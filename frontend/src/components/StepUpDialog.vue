// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { requestStepUp, verifyStepUp, type StepUpPurpose } from '../lib/api'
import { useSessionStore } from '../stores/session'

// PG-203: re-confirmation for destructive actions, as an overlay rather than a
// sign-out and sign-back-in. The session is never touched, so the user keeps
// their place; they just prove they are still the one at the keyboard.
//
// The dialog only collects the code. It does not decide whether the action is
// allowed: the grant token it returns is spent server-side, and the endpoints
// refuse without one. That split matters, because a confirmation the client
// could skip would be theatre.
const props = defineProps<{
  open: boolean
  purpose: StepUpPurpose
  title: string
  /** What the user is about to do, shown above the code field. */
  description: string
  /** Label of the final button, e.g. "Delete my account". */
  confirmLabel: string
  /** Renders the confirm button in red for irreversible actions. */
  destructive?: boolean
}>()

const emit = defineEmits<{
  /** Carries the single-use grant token for the destructive call. */
  (e: 'confirmed', stepUpToken: string): void
  (e: 'close'): void
}>()

const session = useSessionStore()

const method = ref<'totp' | 'email' | null>(null)
const digits = ref(['', '', '', '', '', ''])
const inputs = ref<(HTMLInputElement | null)[]>([])
const requesting = ref(false)
const verifying = ref(false)
const error = ref<string | null>(null)

const code = computed(() => digits.value.join(''))
const complete = computed(() => code.value.length === 6)

const reset = () => {
  method.value = null
  digits.value = ['', '', '', '', '', '']
  error.value = null
  verifying.value = false
}

const start = async () => {
  requesting.value = true
  error.value = null
  try {
    const { method: m } = await requestStepUp(session.idToken!, props.purpose)
    method.value = m
    await nextTick()
    inputs.value[0]?.focus()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Could not start the confirmation.'
  } finally {
    requesting.value = false
  }
}

// Opening the dialog asks the backend which proof applies. Closing resets, so
// a reopened dialog never shows a stale code or a stale error.
watch(
  () => props.open,
  (open) => {
    if (open) {
      reset()
      start()
    } else {
      reset()
    }
  },
)

const onInput = (i: number, event: Event) => {
  const value = (event.target as HTMLInputElement).value.replace(/\D/g, '')
  digits.value[i] = value.slice(-1)
  if (digits.value[i] && i < 5) inputs.value[i + 1]?.focus()
}

const onKeydown = (i: number, event: KeyboardEvent) => {
  if (event.key === 'Backspace' && !digits.value[i] && i > 0) inputs.value[i - 1]?.focus()
}

// Codes arrive by copy-paste at least as often as by typing, and pasting into
// a six-box field is miserable unless it is handled explicitly.
const onPaste = (event: ClipboardEvent) => {
  const pasted = (event.clipboardData?.getData('text') ?? '').replace(/\D/g, '').slice(0, 6)
  if (!pasted) return
  event.preventDefault()
  for (let i = 0; i < 6; i += 1) digits.value[i] = pasted[i] ?? ''
  inputs.value[Math.min(pasted.length, 5)]?.focus()
}

const submit = async () => {
  if (!complete.value || verifying.value) return
  verifying.value = true
  error.value = null
  try {
    const { token } = await verifyStepUp(session.idToken!, props.purpose, code.value)
    emit('confirmed', token)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'That code was not accepted.'
    digits.value = ['', '', '', '', '', '']
    await nextTick()
    inputs.value[0]?.focus()
  } finally {
    verifying.value = false
  }
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 px-4 backdrop-blur-sm"
    role="dialog"
    aria-modal="true"
    :aria-label="title"
    @keydown.esc="emit('close')"
  >
    <div class="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-800 dark:bg-slate-900">
      <h2 class="text-lg font-semibold text-slate-900 dark:text-slate-100">{{ title }}</h2>
      <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ description }}</p>

      <p v-if="requesting" class="mt-6 text-sm text-slate-500 dark:text-slate-400">
        Preparing confirmation…
      </p>

      <template v-else-if="method">
        <p class="mt-6 text-sm font-medium text-slate-700 dark:text-slate-300">
          <template v-if="method === 'totp'">
            Enter the current 6-digit code from your authenticator app.
          </template>
          <template v-else>
            We sent a 6-digit code to your email address. It expires in 10 minutes.
          </template>
        </p>

        <div class="mt-3 flex gap-2" @paste="onPaste">
          <input
            v-for="(digit, i) in digits"
            :key="i"
            :ref="(el) => (inputs[i] = el as HTMLInputElement)"
            :value="digit"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            maxlength="1"
            :aria-label="`Digit ${i + 1} of 6`"
            class="h-12 w-full rounded-lg border border-slate-300 text-center text-lg font-semibold text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            @input="onInput(i, $event)"
            @keydown="onKeydown(i, $event)"
            @keydown.enter="submit"
          />
        </div>
      </template>

      <p v-if="error" class="mt-3 text-sm text-rose-600 dark:text-rose-400">{{ error }}</p>

      <div class="mt-6 flex items-center justify-end gap-3">
        <button
          type="button"
          class="rounded-lg px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
          @click="emit('close')"
        >
          Cancel
        </button>
        <button
          type="button"
          :disabled="!complete || verifying"
          class="rounded-lg px-4 py-2 text-sm font-semibold text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          :class="destructive ? 'bg-rose-600 hover:bg-rose-500' : 'bg-indigo-600 hover:bg-indigo-500'"
          @click="submit"
        >
          {{ verifying ? 'Confirming…' : confirmLabel }}
        </button>
      </div>
    </div>
  </div>
</template>

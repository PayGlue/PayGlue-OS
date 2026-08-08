// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
// First run of a self-hosted installation (PG-237).
//
// Two steps only, then it hands over to the publication onboarding that
// already exists. The mockup drew four; steps three and four are the two
// screens TenantOnboardingView has had all along, and having them twice would
// mean maintaining them twice.
//
// The wizard is reachable only while the installation has no account. That is
// decided by the backend counting rows, never by this file: an open
// registration endpoint on a machine that faces the internet is the easiest
// way there is to lose it.
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { bootstrapFirstAccount, installationNeedsSetup } from '../lib/authProvider'
import { useSessionStore } from '../stores/session'
import PayGlueLogo from '../components/PayGlueLogo.vue'

const router = useRouter()
const session = useSessionStore()

type Mode = 'local' | 'hosted'

const step = ref<1 | 2>(1)
const mode = ref<Mode | null>(null)
const email = ref('')
const password = ref('')
const confirmation = ref('')
const submitting = ref(false)
const error = ref<string | null>(null)

// The one rule that can honestly be shown live. Django also rejects passwords
// that are entirely numeric, too close to the email address, or among the
// twenty thousand most common, and none of those can be judged in the browser
// without shipping the list or guessing. Showing a green tick the server then
// overrules is worse than showing nothing, so the rest arrives as the server's
// own message.
const MIN_LENGTH = 10
const longEnough = computed(() => password.value.length >= MIN_LENGTH)
const matches = computed(() => confirmation.value.length > 0 && password.value === confirmation.value)
const canCreate = computed(
  () => email.value.trim().includes('@') && longEnough.value && matches.value && !submitting.value,
)

const choose = (value: Mode) => {
  mode.value = value
}

const createAccount = async () => {
  if (!canCreate.value) return
  submitting.value = true
  error.value = null
  try {
    await bootstrapFirstAccount(email.value.trim(), password.value)
    await session.bootstrap()
    // Straight into the publication step, which is the same screen every
    // account sees when it has no publication yet.
    router.replace({ name: 'tenant-onboarding' })
  } catch (err) {
    error.value = messageFrom(err)
    submitting.value = false
  }
}

const messageFrom = (err: unknown): string => {
  const response = (err as { response?: { data?: Record<string, unknown> } })?.response
  const data = response?.data
  if (data) {
    // The password validators answer with a list under `password`.
    const fromPassword = data.password
    if (Array.isArray(fromPassword) && fromPassword.length > 0) return String(fromPassword[0])
    if (typeof data.detail === 'string') return data.detail
  }
  return err instanceof Error ? err.message : 'Could not create the account.'
}

// Nothing to do here for a hosted provider: its address and key are read when
// the dashboard is built, so they cannot be typed in now. The honest screen is
// the two lines to put in the environment, and a restart.
const stillNeedsSetup = computed(() => installationNeedsSetup())
</script>

<template>
  <main class="flex min-h-screen items-center justify-center bg-slate-50 px-6 py-12 dark:bg-slate-950">
    <div class="w-full max-w-xl">
      <div class="mb-8 flex items-center gap-3">
        <PayGlueLogo size="lg" />
        <span
          class="ml-auto rounded border border-slate-300 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:border-slate-700 dark:text-slate-400"
        >
          Self-hosted
        </span>
      </div>

      <div class="mb-7 flex gap-1.5">
        <span class="h-[3px] flex-1 rounded bg-indigo-600"></span>
        <span
          class="h-[3px] flex-1 rounded"
          :class="step === 2 ? 'bg-indigo-600' : 'bg-slate-200 dark:bg-slate-800'"
        ></span>
      </div>

      <div
        class="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-800 dark:bg-slate-900"
      >
        <!-- Step 1: how sign-in works here -->
        <template v-if="step === 1">
          <p class="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Step 1 of 2
          </p>
          <h1 class="mb-2 text-2xl font-bold text-slate-900 dark:text-slate-100">
            How do you want to sign in?
          </h1>
          <p class="mb-6 max-w-prose text-sm text-slate-500 dark:text-slate-400">
            PayGlue needs one way to check who you are. Pick the one that matches what you are
            doing with this installation.
          </p>

          <div class="grid gap-3">
            <button
              type="button"
              class="grid grid-cols-[20px_1fr] gap-3.5 rounded-xl border p-4 text-left transition"
              :class="mode === 'local'
                ? 'border-indigo-600 ring-1 ring-inset ring-indigo-600'
                : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:hover:border-slate-700 dark:hover:bg-slate-800/50'"
              @click="choose('local')"
            >
              <span
                class="mt-0.5 grid h-[18px] w-[18px] place-items-center rounded-full border-2"
                :class="mode === 'local' ? 'border-indigo-600' : 'border-slate-400 dark:border-slate-600'"
              >
                <span v-if="mode === 'local'" class="h-2 w-2 rounded-full bg-indigo-600"></span>
              </span>
              <span>
                <span class="block font-semibold text-slate-900 dark:text-slate-100">
                  Just trying it out on this device
                </span>
                <span class="mt-0.5 block text-[13.5px] text-slate-500 dark:text-slate-400">
                  Accounts live in this installation. Nothing to sign up for anywhere else.
                </span>
              </span>
            </button>

            <button
              type="button"
              class="grid grid-cols-[20px_1fr] gap-3.5 rounded-xl border p-4 text-left transition"
              :class="mode === 'hosted'
                ? 'border-indigo-600 ring-1 ring-inset ring-indigo-600'
                : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:hover:border-slate-700 dark:hover:bg-slate-800/50'"
              @click="choose('hosted')"
            >
              <span
                class="mt-0.5 grid h-[18px] w-[18px] place-items-center rounded-full border-2"
                :class="mode === 'hosted' ? 'border-indigo-600' : 'border-slate-400 dark:border-slate-600'"
              >
                <span v-if="mode === 'hosted'" class="h-2 w-2 rounded-full bg-indigo-600"></span>
              </span>
              <span>
                <span class="block font-semibold text-slate-900 dark:text-slate-100">
                  Running this on a server
                </span>
                <span class="mt-0.5 block text-[13.5px] text-slate-500 dark:text-slate-400">
                  Connect an identity provider. Adds magic links, sign-in with Google or GitHub,
                  and authenticator apps.
                </span>
              </span>
            </button>
          </div>

          <p class="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-[13px] text-slate-500 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-400">
            Either way you can run several of your own publications. This choice only affects
            sign-in.
          </p>

          <!-- The licence, as a note rather than a gate. -->
          <div
            class="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
          >
            <p class="mb-1 font-semibold">A word on the licence</p>
            <p>
              PayGlue is source-available under the Business Source License 1.1. You may run it
              for your own purposes, including commercially inside your own business. You may not
              offer it to other people as a hosted or managed service. That needs a commercial
              licence.
            </p>
          </div>

          <!-- Signed by name on purpose. PG-239 took personal attribution out
               of code comments and seeded data, where it had no business being;
               a letter from the person who built the thing is the opposite
               case, and unsigned it would be worth nothing. -->
          <div class="mt-4 rounded-xl border border-slate-200 bg-white px-4 py-4 text-[13px] leading-relaxed text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
            <p class="mb-2 font-semibold text-slate-900 dark:text-slate-100">A letter from the founder</p>
            <p class="mb-2">
              I run my own Ghost blogs and wanted to take payments through providers other than
              Stripe. Ghost said no. So I built the relay I wanted: your payment provider on one
              side, Ghost memberships on the other, and nobody asked to sign up twice in between.
            </p>
            <p class="mb-2">
              You are looking at all of it. This is the same code that runs the hosted product,
              and it is public because a tool sitting between your readers and their money is one
              you should be able to read. What we hold ourselves to while handling it is written
              down as well:
              <a href="https://payglue.io/security" target="_blank" rel="noopener" class="font-semibold text-indigo-600 hover:underline dark:text-indigo-400">our security manifest</a>.
            </p>
            <p class="mb-2">
              If you want to know more:
              <a href="https://payglue.io" target="_blank" rel="noopener" class="font-semibold text-indigo-600 hover:underline dark:text-indigo-400">payglue.io</a>,
              the
              <a href="https://blog.payglue.io" target="_blank" rel="noopener" class="font-semibold text-indigo-600 hover:underline dark:text-indigo-400">blog</a>,
              where we write about what shipped and what we reconsidered, and the
              <a href="https://docs.payglue.io" target="_blank" rel="noopener" class="font-semibold text-indigo-600 hover:underline dark:text-indigo-400">documentation</a>.
            </p>
            <p class="mb-2">
              The code lives at
              <a href="https://github.com/PayGlue/PayGlue-OS" target="_blank" rel="noopener" class="font-semibold text-indigo-600 hover:underline dark:text-indigo-400">github.com/PayGlue/PayGlue-OS</a>,
              with issues and pull requests open. CONTRIBUTING.md says what helps most, and a bug
              report from a real installation is worth as much as a patch.
            </p>
            <p class="mb-2">
              <span class="block font-semibold text-slate-900 dark:text-slate-100">Let&rsquo;s connect:</span>
              <a href="https://x.com/PayGlue_io" target="_blank" rel="noopener" class="font-semibold text-indigo-600 hover:underline dark:text-indigo-400">X</a>,
              <a href="https://www.threads.com/@payglue.io" target="_blank" rel="noopener" class="font-semibold text-indigo-600 hover:underline dark:text-indigo-400">Threads</a>,
              <a href="https://bsky.app/profile/payglue.bsky.social" target="_blank" rel="noopener" class="font-semibold text-indigo-600 hover:underline dark:text-indigo-400">Bluesky</a>
              or find me on
              <a href="https://mastodon.social/@payglue" target="_blank" rel="noopener" class="font-semibold text-indigo-600 hover:underline dark:text-indigo-400">Mastodon</a>.
            </p>
            <p class="mb-2 font-semibold text-slate-500 dark:text-slate-400">#BuildInPublic</p>
            <p class="mt-3">
              Have fun exploring!<br />
              Cheers,<br />
              <em>André</em>
            </p>
          </div>

          <div class="mt-7 flex">
            <button
              type="button"
              class="ml-auto rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-45"
              :disabled="!mode"
              @click="step = 2"
            >
              Continue
            </button>
          </div>
        </template>

        <!-- Step 2a: the first account, kept here -->
        <template v-else-if="mode === 'local'">
          <p class="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Step 2 of 2
          </p>
          <h1 class="mb-2 text-2xl font-bold text-slate-900 dark:text-slate-100">Your account</h1>
          <p class="mb-6 max-w-prose text-sm text-slate-500 dark:text-slate-400">
            The first account is the administrator. Anyone else joins later by invitation only.
          </p>

          <form class="space-y-4" @submit.prevent="createAccount">
            <div>
              <label for="setup-email" class="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">
                Email
              </label>
              <input
                id="setup-email"
                v-model="email"
                type="email"
                autocomplete="username"
                placeholder="you@yourdomain.com"
                class="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
              <p class="mt-1.5 text-xs text-slate-500 dark:text-slate-400">
                Also where a password reset link would be sent, which needs outgoing mail to be
                configured.
              </p>
            </div>

            <div>
              <label for="setup-password" class="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">
                Password
              </label>
              <input
                id="setup-password"
                v-model="password"
                type="password"
                autocomplete="new-password"
                class="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
              <p
                class="mt-1.5 text-xs"
                :class="longEnough
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : 'text-slate-500 dark:text-slate-400'"
              >
                At least {{ MIN_LENGTH }} characters. It also cannot be all digits, too close to
                your email address, or a commonly used password.
              </p>
            </div>

            <div>
              <label for="setup-confirm" class="mb-1.5 block text-sm font-semibold text-slate-700 dark:text-slate-300">
                Confirm password
              </label>
              <input
                id="setup-confirm"
                v-model="confirmation"
                type="password"
                autocomplete="new-password"
                class="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
              <p
                v-if="confirmation.length > 0 && !matches"
                class="mt-1.5 text-xs text-rose-600 dark:text-rose-400"
              >
                The two do not match.
              </p>
            </div>

            <div
              class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-[13px] text-slate-500 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-400"
            >
              <strong class="font-semibold text-slate-700 dark:text-slate-200">
                Authenticator apps are not available in this mode.
              </strong>
              Use a password you use nowhere else, and keep it in a password manager.
            </div>

            <p
              v-if="error"
              class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300"
            >
              {{ error }}
            </p>

            <div class="flex items-center gap-3 pt-1">
              <button
                type="button"
                class="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:border-slate-400 hover:text-slate-900 dark:border-slate-700 dark:text-slate-300"
                @click="step = 1"
              >
                Back
              </button>
              <button
                type="submit"
                class="ml-auto rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-45"
                :disabled="!canCreate"
              >
                {{ submitting ? 'Creating...' : 'Create account' }}
              </button>
            </div>
          </form>
        </template>

        <!-- Step 2b: pointing at an identity provider, which is a restart, not a form -->
        <template v-else>
          <p class="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Step 2 of 2
          </p>
          <h1 class="mb-2 text-2xl font-bold text-slate-900 dark:text-slate-100">
            Connect an identity provider
          </h1>
          <p class="mb-6 max-w-prose text-sm text-slate-500 dark:text-slate-400">
            This one cannot be done from here. The dashboard reads these when it is built, so they
            belong in the environment and take effect after a restart.
          </p>

          <p class="mb-2 text-sm font-semibold text-slate-700 dark:text-slate-300">
            Put these in your <code class="rounded bg-slate-100 px-1.5 py-0.5 text-[13px] dark:bg-slate-800">.env</code>:
          </p>
          <pre class="overflow-x-auto rounded-xl bg-slate-900 px-4 py-3 text-[13px] leading-relaxed text-slate-100 dark:bg-slate-950"><code>VITE_SUPABASE_URL=https://xxxxxxxx.supabase.co
VITE_SUPABASE_ANON_KEY=sb_publishable_...
LOCAL_AUTH_ENABLED=0</code></pre>

          <p class="mt-3 text-xs text-slate-500 dark:text-slate-400">
            Both values are in the Supabase dashboard under Project Settings, API. The publishable
            key is the one meant for the browser; the service role key does not belong here.
          </p>

          <div
            class="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-[13px] text-slate-500 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-400"
          >
            After the restart this screen is replaced by the normal sign-in page, and you create
            your first account in Supabase itself.
          </div>

          <div class="mt-7 flex items-center gap-3">
            <button
              type="button"
              class="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:border-slate-400 hover:text-slate-900 dark:border-slate-700 dark:text-slate-300"
              @click="step = 1"
            >
              Back
            </button>
          </div>
        </template>
      </div>

      <p
        v-if="!stillNeedsSetup"
        class="mt-6 text-center text-sm text-slate-500 dark:text-slate-400"
      >
        This installation already has an account.
        <RouterLink to="/login" class="font-semibold text-indigo-600 hover:underline dark:text-indigo-400">
          Sign in
        </RouterLink>
      </p>
    </div>
  </main>
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import {
  createSupportRequest,
  generateServicePin,
  getServicePin,
  listSupportRequests,
  revokeServicePin,
} from '../lib/api'
import { useSessionStore } from '../stores/session'
import type { ServicePin, SupportRequestSummary } from '../types/api'

const session = useSessionStore()

const canManagePin = computed(() => {
  const role = session.activeMembership?.role
  return role === 'owner' || role === 'admin'
})

const servicePin = ref<ServicePin | null>(null)
const pinLoading = ref(false)
const pinError = ref<string | null>(null)
const pinCopied = ref(false)

const loadServicePin = async () => {
  if (!session.activeTenantSlug || !session.idToken) return
  try {
    servicePin.value = await getServicePin(session.activeTenantSlug, session.idToken)
  } catch {
    // non-fatal, section just shows the empty state
  }
}

const generatePin = async () => {
  if (!session.activeTenantSlug || !session.idToken) return
  pinLoading.value = true
  pinError.value = null
  try {
    servicePin.value = await generateServicePin(session.activeTenantSlug, session.idToken)
  } catch (e) {
    pinError.value = e instanceof Error ? e.message : 'Could not generate a service PIN.'
  } finally {
    pinLoading.value = false
  }
}

const revokePin = async () => {
  if (!session.activeTenantSlug || !session.idToken) return
  pinLoading.value = true
  pinError.value = null
  try {
    await revokeServicePin(session.activeTenantSlug, session.idToken)
    servicePin.value = null
  } catch (e) {
    pinError.value = e instanceof Error ? e.message : 'Could not revoke the service PIN.'
  } finally {
    pinLoading.value = false
  }
}

const copyPin = async () => {
  if (!servicePin.value) return
  await navigator.clipboard.writeText(servicePin.value.code)
  pinCopied.value = true
  setTimeout(() => { pinCopied.value = false }, 2000)
}

const formatExpiry = (iso: string) => {
  try { return new Date(iso).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' }) }
  catch { return iso }
}

onMounted(() => {
  loadServicePin()
  loadRequests()
})

// Contact form. Unlike the public site's contact page this posts to our
// own backend, because in here we know the tenant and the signed-in address,
// which is what lets a request get a reference number and a status.
const name = ref('')
const email = ref(session.user?.email ?? '')
const message = ref('')
const sent = ref(false)
const sending = ref(false)

// Creem-style topic cards. Two jobs: the sender picks the right lane, and the
// inbox gets a subject line that says what this is before it is opened.
// Purely a label -- it never gates the form, because somebody whose category
// does not fit still has a problem worth hearing.
const TOPICS = [
  { key: 'integration', label: 'Integration issue', hint: 'Ghost, a provider, or a mapping is not behaving', icon: 'M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244' },
  { key: 'billing', label: 'Billing or plan', hint: 'Invoices, upgrades, downgrades, cancellation', icon: 'M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3M3.75 19.5h16.5A2.25 2.25 0 0022.5 17.25v-10.5A2.25 2.25 0 0020.25 4.5H3.75A2.25 2.25 0 001.5 6.75v10.5A2.25 2.25 0 003.75 19.5z' },
  { key: 'bug', label: 'Something is broken', hint: 'An error, a page that will not load, wrong data', icon: 'M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z' },
  { key: 'feature', label: 'Feature or provider request', hint: 'Something missing you would use', icon: 'M12 18v-5.25m0 0a6.01 6.01 0 001.5-.189m-1.5.189a6.01 6.01 0 01-1.5-.189m3.75 7.478a12.06 12.06 0 01-4.5 0m3.75 2.383a14.406 14.406 0 01-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 10-7.517 0c.85.493 1.509 1.333 1.509 2.316V18' },
  { key: 'account', label: 'Account or team', hint: 'Access, roles, ownership, deletion', icon: 'M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z' },
  { key: 'other', label: 'Something else', hint: 'Anything the categories above do not cover', icon: 'M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z' },
] as const

const topic = ref<string>('')
const contactError = ref<string | null>(null)

const canSubmit = () =>
  name.value.trim().length > 0 &&
  email.value.trim().includes('@') &&
  message.value.trim().length > 0

async function submitContact() {
  if (!canSubmit()) return
  if (!session.activeTenantSlug || !session.idToken) return
  sending.value = true
  contactError.value = null
  try {
    const created = await createSupportRequest(session.activeTenantSlug, session.idToken, {
      name: name.value,
      message: message.value,
      topic: topic.value,
    })
    reference.value = created.reference
    requests.value = [created, ...requests.value]
    sent.value = true
  } catch {
    contactError.value = 'Something went wrong. Please email us directly.'
  } finally {
    sending.value = false
  }
}

// The reference the customer just earned, shown on the success panel and
// repeated in their confirmation email so both agree.
const reference = ref<string | null>(null)

// History. Status only, never the conversation: the Linear issue it mirrors
// also carries our internal comments.
const requests = ref<SupportRequestSummary[]>([])
const requestsLoading = ref(false)

const loadRequests = async () => {
  if (!session.activeTenantSlug || !session.idToken) return
  requestsLoading.value = true
  try {
    requests.value = await listSupportRequests(session.activeTenantSlug, session.idToken)
  } catch {
    // Non-fatal. The form above still works, and a missing history is a much
    // smaller problem than a support page that will not load.
  } finally {
    requestsLoading.value = false
  }
}

const STATUS_STYLES: Record<string, string> = {
  open: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  in_progress: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300',
  done: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
  cancelled: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500',
}

const topicLabel = (key: string) =>
  TOPICS.find((t) => t.key === key)?.label ?? 'General question'

const formatDate = (iso: string) => {
  try { return new Date(iso).toLocaleDateString('de-DE', { dateStyle: 'medium' }) }
  catch { return iso }
}

</script>

<template>
  <AppShell>
    <div class="space-y-6">

      <!-- Service PIN -->
      <!-- Amber, not grey: this authorises somebody else to change your account.
           It was previously indistinguishable from the rest of the page, so it
           read as a step everybody has to take, which is the opposite of true. -->
      <section v-if="canManagePin" class="rounded-2xl border border-amber-200 bg-amber-50 p-5 dark:border-amber-500/30 dark:bg-amber-500/10">
        <div class="flex items-start gap-3">
          <svg class="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-600 dark:text-amber-400" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <div>
            <h2 class="text-base font-semibold text-amber-900 dark:text-amber-200">
              Support access PIN
              <span class="ml-2 rounded-md bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-500/20 dark:text-amber-200">Only when we ask</span>
            </h2>
            <p class="mt-1.5 text-sm leading-relaxed text-amber-900/80 dark:text-amber-200/80">
              <strong>You do not need this for a normal question.</strong> A PIN authorises us to make active changes to your account while working on a ticket. We can already read logs and debug without one. Generate it only if we ask, and send it by email. It expires after 24 hours, and you can revoke it the moment the ticket is done.
            </p>
          </div>
        </div>

        <p v-if="pinError" class="mt-3 text-sm text-rose-700 dark:text-rose-300">{{ pinError }}</p>

        <div v-if="servicePin" class="mt-4 flex flex-wrap items-center gap-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 dark:border-slate-800 dark:bg-slate-800/40 px-4 py-3">
          <button
            type="button"
            class="inline-flex items-center gap-2 rounded-lg bg-white border border-slate-300 dark:border-slate-700 px-3 py-1.5 font-mono text-sm font-semibold text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            :title="pinCopied ? 'Copied!' : 'Copy to clipboard'"
            @click="copyPin"
          >
            {{ servicePin.code }}
            <svg v-if="!pinCopied" class="h-3.5 w-3.5 text-slate-400 dark:text-slate-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
            <svg v-else class="h-3.5 w-3.5 text-emerald-500" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
            </svg>
          </button>
          <span class="text-xs text-slate-500 dark:text-slate-400">Valid until {{ formatExpiry(servicePin.expires_at) }}</span>
          <button
            type="button"
            class="ml-auto rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800 disabled:opacity-50"
            :disabled="pinLoading"
            @click="revokePin"
          >
            {{ pinLoading ? 'Revoking...' : 'Revoke' }}
          </button>
        </div>
        <div v-else class="mt-4">
          <button
            type="button"
            class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="pinLoading"
            @click="generatePin"
          >
            {{ pinLoading ? 'Generating...' : 'Generate service PIN' }}
          </button>
        </div>
      </section>

      <!-- Contact form -->
      <section class="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="text-base font-semibold text-slate-900 dark:text-slate-100">Contact support</h2>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Questions or an issue with your integration? We read everything and reply personally to
          <a class="text-indigo-600 dark:text-indigo-400 hover:underline" href="mailto:team@payglue.io">team@payglue.io</a>.
        </p>

        <!-- Topic cards first: picking the lane is easier than writing the
             first sentence, and it gets the reader moving. -->
        <div v-if="!sent" class="mt-5 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          <button
            v-for="t in TOPICS"
            :key="t.key"
            type="button"
            class="flex items-start gap-3 rounded-xl border p-3.5 text-left transition-all"
            :class="topic === t.key
              ? 'border-indigo-500 bg-indigo-50 ring-1 ring-indigo-500 dark:bg-indigo-500/10'
              : 'border-slate-200 bg-white hover:border-indigo-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-indigo-500/50'"
            @click="topic = t.key"
          >
            <span
              class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg"
              :class="topic === t.key
                ? 'bg-indigo-100 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-300'
                : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'"
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" :d="t.icon" />
              </svg>
            </span>
            <span class="min-w-0">
              <span class="block text-sm font-semibold text-slate-900 dark:text-slate-100">{{ t.label }}</span>
              <span class="mt-0.5 block text-xs leading-relaxed text-slate-500 dark:text-slate-400">{{ t.hint }}</span>
            </span>
          </button>
        </div>

        <div v-if="!sent" class="mt-6 grid gap-6 lg:grid-cols-3">
          <!-- The form used to sit at max-w-xl inside a full-width card, which
               left two thirds of the row empty and made it look like an
               afterthought. It now shares the row with the self-serve answer. -->
          <div class="space-y-4 lg:col-span-2">
          <div>
            <label class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-200" for="support-name">Name</label>
            <input
              id="support-name"
              v-model="name"
              required
              type="text"
              placeholder="Your name"
              class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
            />
          </div>
          <div>
            <label class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-200" for="support-email">Email</label>
            <input
              id="support-email"
              v-model="email"
              required
              type="email"
              placeholder="you@example.com"
              class="w-full rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
            />
          </div>
          <div>
            <label class="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-200" for="support-message">Message</label>
            <textarea
              id="support-message"
              v-model="message"
              required
              rows="5"
              placeholder="What's going on?"
              class="w-full resize-none rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
            ></textarea>
          </div>
          <p v-if="contactError" class="rounded-lg bg-rose-50 dark:bg-rose-500/10 px-4 py-3 text-sm text-rose-700 dark:text-rose-300">
            {{ contactError }} <a href="mailto:team@payglue.io" class="underline">team@payglue.io</a>
          </p>
          <button
            type="button"
            :disabled="!canSubmit() || sending"
            class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            @click="submitContact"
          >
            {{ sending ? 'Sending...' : 'Send message' }}
          </button>
          </div>

          <!-- The self-serve answer, beside the form rather than after it. Most
               questions have a written answer already; offering it here costs a
               reply for us and a wait for them. -->
          <aside class="space-y-4">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-800/40">
              <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-100 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-300">
                <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                </svg>
              </div>
              <p class="mt-3 text-sm font-semibold text-slate-900 dark:text-slate-100">Have you checked the docs?</p>
              <p class="mt-1.5 text-sm leading-relaxed text-slate-500 dark:text-slate-400">
                Setup guides for every provider, the Ghost connection, paywalls and buy buttons. Usually faster than waiting for a reply.
              </p>
              <a
                href="https://docs.payglue.io"
                target="_blank"
                rel="noopener"
                class="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-indigo-600 hover:underline dark:text-indigo-400"
              >
                Open the docs
                <span aria-hidden="true">&#8594;</span>
              </a>
            </div>

            <div class="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
              <p class="text-sm font-semibold text-slate-900 dark:text-slate-100">Also worth a look</p>
              <ul class="mt-2.5 space-y-2 text-sm">
                <li>
                  <a href="https://payglue.io/changelog" target="_blank" rel="noopener" class="text-indigo-600 hover:underline dark:text-indigo-400">Changelog</a>
                  <span class="text-slate-500 dark:text-slate-400"> if something changed recently</span>
                </li>
                <li>
                  <a href="https://payglue.io/roadmap" target="_blank" rel="noopener" class="text-indigo-600 hover:underline dark:text-indigo-400">Roadmap</a>
                  <span class="text-slate-500 dark:text-slate-400"> before asking for a feature</span>
                </li>
                <li>
                  <a href="https://status.payglue.io" target="_blank" rel="noopener" class="text-indigo-600 hover:underline dark:text-indigo-400">System status</a>
                  <span class="text-slate-500 dark:text-slate-400"> if it broke all at once</span>
                </li>
              </ul>
            </div>
          </aside>
        </div>

        <div v-else class="mt-4 flex flex-col items-center justify-center rounded-2xl border border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 p-10 text-center">
          <div class="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-2xl text-emerald-600 dark:text-emerald-400">&#10003;</div>
          <h3 class="mb-1 text-base font-semibold text-slate-900 dark:text-slate-100">Message sent.</h3>
          <p class="text-sm text-slate-500 dark:text-slate-400">We got your message and will reply personally. Check your inbox for a confirmation copy.</p>
          <p v-if="reference" class="mt-4 text-sm text-slate-600 dark:text-slate-300">
            Your reference is
            <span class="ml-1 rounded-md bg-white dark:bg-slate-900 px-2 py-1 font-mono text-sm font-semibold text-slate-900 dark:text-slate-100 ring-1 ring-emerald-200 dark:ring-emerald-500/30">{{ reference }}</span>
          </p>
          <p v-if="reference" class="mt-2 text-xs text-slate-500 dark:text-slate-400">Quote it in any reply and everything stays on one thread.</p>
        </div>

        <!-- History. Deliberately status only: the Linear issue behind each of
             these also carries our internal notes, so the conversation itself
             stays in email where it belongs. -->
        <div v-if="requests.length" class="mt-8">
          <h3 class="text-sm font-semibold text-slate-900 dark:text-slate-100">Your requests</h3>
          <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Where each one stands. Replies still come by email.
          </p>
          <ul class="mt-3 divide-y divide-slate-200 dark:divide-slate-800 overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
            <li
              v-for="request in requests"
              :key="request.id"
              class="flex flex-wrap items-center gap-x-4 gap-y-1 bg-white dark:bg-slate-900 px-4 py-3"
            >
              <span class="font-mono text-xs font-semibold text-slate-900 dark:text-slate-100">{{ request.reference }}</span>
              <span class="flex-1 truncate text-sm text-slate-600 dark:text-slate-300">{{ topicLabel(request.topic) }}</span>
              <span class="text-xs text-slate-400 dark:text-slate-500">{{ formatDate(request.created_at) }}</span>
              <span
                class="rounded-full px-2.5 py-0.5 text-xs font-medium"
                :class="STATUS_STYLES[request.status]"
              >{{ request.status_label }}</span>
            </li>
          </ul>
        </div>
      </section>

    </div>
  </AppShell>
</template>

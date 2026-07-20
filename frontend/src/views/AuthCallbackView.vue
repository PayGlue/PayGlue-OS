// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { supabase } from '../lib/supabase'

const router = useRouter()
const isTakingAWhile = ref(false)

// Supabase auto-links a new OAuth identity to an existing account when the
// verified email matches (no confirmation step is possible on our end for a
// one-click social button -- we only find out the email after the redirect
// completes). Flag it here so AppShell can show a one-time "we linked your
// account" notice instead of silently switching the user's login method.
const flagIfIdentityWasJustLinked = (user: { identities?: { provider: string; created_at?: string }[] | null }) => {
  const identities = user.identities ?? []
  if (identities.length < 2) return
  const newest = identities.reduce((a, b) => {
    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
    const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
    return bTime > aTime ? b : a
  })
  const ageMs = newest.created_at ? Date.now() - new Date(newest.created_at).getTime() : Infinity
  if (ageMs < 2 * 60 * 1000) {
    sessionStorage.setItem('payglue:just-linked-provider', newest.provider)
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

// Confirmed live (PG-142): Supabase writes the flow_state row backing this
// exchange (auth_code_issued_at) via its /verify redirect, but querying it
// back out immediately (as our own exchange does, milliseconds later) fails
// with "invalid flow state, no valid flow state found" even though the row
// demonstrably exists in Postgres with a matching auth_code and
// code_challenge at that exact moment (verified directly via SQL). This is
// read-after-write lag on Supabase's own infra for this project -- much
// longer than typical: a short retry window (a couple of attempts within
// ~1.5s) was NOT enough and still failed every time. Directly measured via
// hand-crafted requests bypassing our own frontend entirely: exchanging the
// same code after a deliberate ~20s wait succeeds cleanly. This lines up
// with why Google/GitHub OAuth sign-in on this project has been working all
// along -- the provider consent screen naturally takes several seconds,
// giving the lag time to resolve, while magic link normally exchanges in
// under a second.
//
// gotrue-js deletes the `<storageKey>-code-verifier` localStorage entry
// after every exchangeCodeForSession call, success or failure, so a naive
// retry finds no verifier on attempt 2 and fails differently (verifier
// missing instead of flow state). Snapshot it up front and restore it
// before each retry.
const RETRY_DELAYS_MS = [1000, 2000, 4000, 6000, 8000, 8000]

const exchangeWithRetry = async (url: string) => {
  const verifierKey = Object.keys(localStorage).find((k) => k.endsWith('-auth-token-code-verifier'))
  const verifierValue = verifierKey ? localStorage.getItem(verifierKey) : null

  let last = await supabase.auth.exchangeCodeForSession(url)
  for (const delay of RETRY_DELAYS_MS) {
    if (!last.error?.message?.toLowerCase().includes('flow state')) break
    isTakingAWhile.value = true
    await sleep(delay)
    if (verifierKey && verifierValue) localStorage.setItem(verifierKey, verifierValue)
    last = await supabase.auth.exchangeCodeForSession(url)
  }
  return last
}

onMounted(async () => {
  // Exchange the code/token from the URL (PKCE flow or magic link hash)
  const { data, error } = await exchangeWithRetry(window.location.href)
  if (error || !data.session) {
    // Fallback: check if session already exists (e.g. hash-based flow handled by client)
    const { data: existing } = await supabase.auth.getSession()
    if (!existing.session) {
      // Surface the real reason instead of silently bouncing to a blank
      // login page -- the most common cause is a one-time link that was
      // already consumed (e.g. an email provider's link-preview scanner
      // opening it before the user does) or genuinely expired.
      router.replace({
        name: 'login',
        query: { error: error?.message || 'This sign-in link is invalid or has expired. Please request a new one.' },
      })
      return
    }
    flagIfIdentityWasJustLinked(existing.session.user)
  } else {
    flagIfIdentityWasJustLinked(data.session.user)
    // A password-recovery link lands here too (redirectTo has to point
    // somewhere that actually exchanges the code -- /auth/reset never did,
    // it only checked getSession() and relied on detectSessionInUrl to
    // have already populated it, which we turned off in #117). Send
    // recovery flows to the "choose a new password" screen instead of the
    // dashboard now that a session genuinely exists.
    //
    // exchangeCodeForSession's public return type (AuthTokenResponse) omits
    // redirectType, but the actual runtime object always has it -- it's
    // only stripped from the public signature; the private implementation
    // returns { session, user, redirectType } verbatim.
    const redirectType = (data as { redirectType?: string | null }).redirectType
    if (redirectType === 'recovery') {
      router.replace({ name: 'auth-reset' })
      return
    }
  }
  router.replace({ name: 'tenant-select' })
})
</script>

<template>
  <main class="flex min-h-screen flex-col items-center justify-center gap-2 bg-white">
    <p class="text-sm text-slate-500">Signing you in...</p>
    <p v-if="isTakingAWhile" class="text-xs text-slate-400">This is taking a little longer than usual, hang tight.</p>
  </main>
</template>

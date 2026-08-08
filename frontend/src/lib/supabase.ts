// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string

/** Whether this build has a hosted identity provider behind it at all. */
export const supabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey)

const client: SupabaseClient | null = supabaseConfigured
  ? createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        // AuthCallbackView is the single dedicated consumer of the PKCE
        // code/verifier pair. Leaving this on races the SDK's own automatic
        // exchange (fired on client construction) against AuthCallbackView's
        // manual exchangeCodeForSession call -- both redeem the same one-time
        // code, so whichever runs second always fails with "invalid request:
        // both auth code and code verifier should be non-empty", even for a
        // genuine same-browser click on a fresh magic link.
        detectSessionInUrl: false,
        // Without this, gotrue-js's DEFAULT_OPTIONS.flowType ('implicit')
        // applies, so signInWithOtp/signUp never generate or store a
        // code_verifier -- but Supabase's own /auth/v1/verify redirect still
        // hands back a PKCE `code`, which exchangeCodeForSession then has no
        // verifier to redeem. That produced the exact same "code verifier
        // should be non-empty" error on every single attempt, deterministically,
        // independent of the detectSessionInUrl race above.
        flowType: 'pkce',
      },
    })
  : null

// This module used to throw on import when the two variables were missing,
// which is why an installation without a Supabase project could not even boot
// (PG-237). It no longer does. Reaching for the client while it does not exist
// still fails, and loudly, but only at the moment somebody actually uses it,
// and the parts of the interface that need it are gated on `capabilities`
// in lib/authProvider.ts so that never happens by accident.
//
// A Proxy rather than `SupabaseClient | null` on purpose: null would push a
// check into all thirty-odd call sites for a case that the gating already
// rules out, and every one of those checks would be dead code in the hosted
// build.
export const supabase: SupabaseClient = (client ??
  new Proxy({} as SupabaseClient, {
    get() {
      throw new Error(
        'This installation has no Supabase project configured. ' +
          'Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY, or use accounts on ' +
          'this server instead.',
      )
    },
  })) as SupabaseClient

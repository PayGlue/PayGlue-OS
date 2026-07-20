// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error('Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY in environment')
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
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

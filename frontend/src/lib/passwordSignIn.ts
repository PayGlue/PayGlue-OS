// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

/**
 * Which addresses sign in with a password instead of a magic link.
 *
 * Sign-in normally goes through a magic link. Some operators want a small set
 * of accounts that can sign in with a password directly, typically their own,
 * so that setting up and testing accounts does not depend on receiving mail.
 *
 * The list used to be three literals in LoginView and SignupView, including a
 * personal address. That shipped in the open-source build, which told everyone
 * reading it which addresses take the password path on the hosted product.
 * It now comes from the environment and is empty unless configured, so a
 * self-hosted install has no such accounts until its operator names some.
 *
 * `VITE_PASSWORD_SIGNIN_EMAILS` takes a comma-separated list. `*` stands for
 * any run of characters inside the local part, which covers the three shapes
 * that come up:
 *
 *   me@example.com      one specific address
 *   me+*@example.com    plus-addressing, one mailbox, many accounts
 *   *@example.com       every address on a domain
 */

function toMatcher(entry: string): RegExp | null {
  const trimmed = entry.trim().toLowerCase()
  if (!trimmed) return null
  // Escape everything, then turn the escaped star back into a wildcard that
  // cannot jump across the @ and match a different domain than intended.
  const escaped = trimmed.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`^${escaped.replace(/\\\*/g, '[^@]*')}$`)
}

const MATCHERS: RegExp[] = ((import.meta.env.VITE_PASSWORD_SIGNIN_EMAILS as string | undefined) ?? '')
  .split(',')
  .map(toMatcher)
  .filter((r): r is RegExp => r !== null)

/** True when this address should be offered the password form. */
export function usesPasswordSignIn(email: string): boolean {
  const normalized = email.trim().toLowerCase()
  if (!normalized) return false
  return MATCHERS.some(re => re.test(normalized))
}

/** Exported for tests, which need matchers other than the configured ones. */
export function buildMatchers(raw: string): RegExp[] {
  return raw.split(',').map(toMatcher).filter((r): r is RegExp => r !== null)
}

export function matchesAny(matchers: RegExp[], email: string): boolean {
  const normalized = email.trim().toLowerCase()
  if (!normalized) return false
  return matchers.some(re => re.test(normalized))
}

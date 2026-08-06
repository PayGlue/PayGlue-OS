// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

/**
 * The two public addresses this installation is reachable at.
 *
 * Both used to be the literal payglue.io hosts, spread across seven views. The
 * consequence was not cosmetic: the embed snippet a self-hosted operator copied
 * out of their own dashboard read
 * `<script src="https://api.payglue.io/paywall.js">`, so their readers' browsers
 * called our servers instead of theirs, and the webhook URL they handed their
 * payment provider pointed at us too (PG-238).
 *
 * `apiBaseUrl()` is the backend origin. It ends up in embed snippets and webhook
 * URLs, so it has to be the address the outside world can reach, which is not
 * necessarily the one the dashboard is served from.
 *
 * `appBaseUrl()` is where the dashboard itself lives, used for display and for
 * links back into it.
 *
 * Both fall back sensibly so that an install serving everything from one origin
 * needs no configuration at all.
 */

const trim = (value: string | undefined): string => (value ?? '').trim().replace(/\/+$/, '')

const CONFIGURED_API = trim(import.meta.env.VITE_PUBLIC_API_BASE_URL as string | undefined)
const CONFIGURED_APP = trim(import.meta.env.VITE_PUBLIC_APP_BASE_URL as string | undefined)
// The dashboard's own API client already has one of these. Reusing it means the
// common single-backend setup only has to be configured once.
const CLIENT_API = trim(import.meta.env.VITE_API_BASE_URL as string | undefined)

const currentOrigin = (): string => {
  if (typeof window === 'undefined' || !window.location) return ''
  return trim(window.location.origin)
}

/** Backend origin, without a trailing slash. */
export function apiBaseUrl(): string {
  return CONFIGURED_API || CLIENT_API || currentOrigin()
}

/** Dashboard origin, without a trailing slash. */
export function appBaseUrl(): string {
  return CONFIGURED_APP || currentOrigin()
}

/** Dashboard origin without the scheme, for places that show a bare address. */
export function appDisplayHost(): string {
  return appBaseUrl().replace(/^https?:\/\//, '')
}

/**
 * The address this installation answers support mail at, or an empty string.
 *
 * Empty on purpose when unset. The three places that offer a support contact
 * used to name ours, so an unrelated installation invited its own customers to
 * write to us about a product we do not run for them (PG-239). Callers hide the
 * contact rather than substitute a stand-in.
 */
export function supportEmail(): string {
  return ((import.meta.env.VITE_SUPPORT_EMAIL as string | undefined) ?? '').trim()
}

/** The `<script>` tag that embeds one of the public assets. */
export function embedScript(file: string, attributes: Record<string, string>): string {
  const attrs = Object.entries(attributes)
    .map(([key, value]) => ` ${key}="${value}"`)
    .join('')
  return `<script src="${apiBaseUrl()}/${file}"${attrs}><\/script>`
}

/** The webhook URL a payment provider has to call. */
export function webhookUrl(provider: string, tenantSlug: string, key?: string | null): string {
  const base = `${apiBaseUrl()}/webhooks/${provider}?tenant=${tenantSlug}`
  return key ? `${base}&key=${key}` : base
}

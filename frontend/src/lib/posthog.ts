// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

// The live client, once consent has been given. Kept at module scope so
// captureEvent() below can reach it without importing posthog-js itself --
// that import must stay inside loadPostHog(), or the bundle pulls PostHog in
// for visitors who never consented.
type PostHogClient = Awaited<typeof import('posthog-js')>['default']

let loaded = false
let client: PostHogClient | null = null

// Configured per deployment. Without a key nothing loads and every function
// below is a no-op, which is what a self-hosted install gets by default: this
// module used to carry our own project key and relay host as literals, so any
// build of it would have sent someone else's product analytics to us.
const PROJECT_KEY = (import.meta.env.VITE_POSTHOG_KEY as string | undefined) ?? ''
const API_HOST = (import.meta.env.VITE_POSTHOG_HOST as string | undefined) ?? ''
const UI_HOST = (import.meta.env.VITE_POSTHOG_UI_HOST as string | undefined) ?? ''

/** True when this deployment has analytics configured at all. */
export const analyticsConfigured = () => PROJECT_KEY !== ''

export const loadPostHog = async () => {
  if (loaded || !PROJECT_KEY) return
  loaded = true

  const { default: posthog } = await import('posthog-js')
  posthog.init(PROJECT_KEY, {
    // A reverse proxy on your own domain keeps ad-blockers that block
    // posthog.com from blocking ingestion outright. Optional: without it
    // posthog-js talks to PostHog directly.
    ...(API_HOST ? { api_host: API_HOST } : {}),
    ...(UI_HOST ? { ui_host: UI_HOST } : {}),
    defaults: '2026-05-30',
    person_profiles: 'identified_only',
    // Consent is already handled by our own cookie-consent banner before
    // this file is ever loaded -- don't show PostHog's own banner too.
    opt_out_capturing_by_default: false,
    // Unhandled errors from real visitors' browsers. Without this, the only
    // frontend bugs we hear about are the ones somebody bothers to report, and
    // most people just leave. Enabled only now that the consent copy and the
    // privacy policy name error monitoring as its own purpose -- it collects
    // messages and stack traces, which is not the same as product analytics.
    capture_exceptions: true,
  })
  client = posthog
}

/**
 * Record a custom event, if and only if analytics consent was given.
 *
 * Analytics is opt-in and off by default, so this is a no-op for most
 * visitors and `client` may still be null while the dynamic import is in
 * flight. Both are silent on purpose: analytics must never be the reason a
 * button stops working.
 *
 * Consequence worth remembering when reading any funnel built on these
 * events: they count consenting visitors only, so absolute numbers are a
 * floor, not the truth. Ratios between steps stay meaningful.
 */
export const captureEvent = (
  event: string,
  properties?: Record<string, unknown>,
  options?: { transport?: 'XHR' | 'fetch' | 'sendBeacon'; send_instantly?: boolean },
) => {
  try {
    client?.capture(event, properties, options)
  } catch {
    // Ignored deliberately: see above.
  }
}

/**
 * Somebody clicked through to a Creem checkout.
 *
 * This is the closest thing to a purchase we can observe ourselves. The
 * checkout itself happens on Creem's domain, where our SDK cannot follow, so
 * the funnel this feeds ends at intent rather than at payment.
 *
 * Both options below matter, and neither alone is enough. PostHog batches
 * events and was measured here taking several seconds to flush, while this
 * click navigates away immediately -- a queued event would frequently die with
 * the page, and losing exactly the click we care about would make the funnel
 * lie in the flattering direction. `send_instantly` skips the queue,
 * `transport` picks a channel that survives unload. Setting only the transport
 * changes how it is sent, not when, so the event still sat in the queue.
 */
export const captureCheckoutStarted = (
  source: 'landing' | 'founding',
  tierPrice: number,
) => {
  captureEvent(
    'checkout_started',
    { source, tier_price: tierPrice, plan: 'founding' },
    { send_instantly: true, transport: 'sendBeacon' },
  )
}

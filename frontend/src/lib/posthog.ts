// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

/**
 * No product analytics. This build sends nothing, anywhere, ever.
 *
 * The dashboard calls captureEvent from a module-level import, so the calls
 * cannot simply be deleted without editing every caller and re-editing them on
 * the next sync from upstream. This file is the seam instead: the same four
 * exports, all of them no-ops, no analytics package in package.json, and no
 * network call to opt out of.
 *
 * Maintained by hand and never overwritten by the sync. If the upstream file
 * grows an export, it has to be added here too, or the build fails on an
 * unresolved import.
 *
 * To put analytics into your own installation, replace this file. The
 * signatures below are the entire contract the rest of the code relies on.
 */

/** Always false: there is nothing to configure. */
export const analyticsConfigured = (): boolean => false

/** Does nothing, so callers need not know whether analytics exist. */
export const loadPostHog = async (): Promise<void> => {}

/** Does nothing. */
export const captureEvent = (
  _event: string,
  _properties?: Record<string, unknown>,
  _options?: { transport?: 'XHR' | 'fetch' | 'sendBeacon'; send_instantly?: boolean },
): void => {}

/** Does nothing. */
export const captureCheckoutStarted = (
  _source: 'landing' | 'founding',
  _tierPrice: number,
): void => {}

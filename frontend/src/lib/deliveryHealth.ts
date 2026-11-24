// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
/**
 * How the dashboard words a delivery state. Words and colours only.
 *
 * PG-402: this file used to classify events itself, and so did the dashboard
 * pill, the activity feed, the events page and the connections overview, each
 * a little differently. One Digistore24 delivery read "All systems healthy",
 * "0 All delivered", "1 retrying" and a red "Delivery failed" on one screen.
 * The backend decides the state now (webhooks/delivery_state.py) and every
 * page reads `delivery_state` or the events/health summary. What is left here
 * is how to say it, so the same state is the same word everywhere.
 */
import type { DeliveryHealthSummary, DeliveryState, NeedsYouGroup } from '../types/api'

export type Tone = 'good' | 'warn' | 'bad' | 'neutral'

export const DELIVERY_LABELS: Record<DeliveryState, string> = {
  delivered: 'Synced',
  skipped: 'Skipped',
  scheduled: 'Scheduled',
  in_flight: 'Processing',
  retrying: 'Retrying',
  rejected: 'Rejected',
  test: 'Test purchase',
  needs_you: 'Needs you',
}

export const DELIVERY_TONES: Record<DeliveryState, Tone> = {
  delivered: 'good',
  skipped: 'neutral',
  scheduled: 'neutral',
  in_flight: 'neutral',
  retrying: 'warn',
  rejected: 'neutral',
  test: 'neutral',
  needs_you: 'bad',
}

/** Tag classes per tone, for the small pills in lists. */
export const TONE_TAG: Record<Tone, string> = {
  good: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
  warn: 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
  bad: 'bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300',
  neutral: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
}

export const TONE_DOT: Record<Tone, string> = {
  good: 'bg-emerald-500',
  warn: 'bg-amber-500',
  bad: 'bg-rose-500',
  neutral: 'bg-slate-300 dark:bg-slate-600',
}

export const PROVIDER_LABELS: Record<string, string> = {
  polar: 'Polar',
  lemonsqueezy: 'Lemon Squeezy',
  paypal: 'PayPal',
  gumroad: 'Gumroad',
  paddle: 'Paddle',
  kofi: 'Ko-fi',
  creem: 'Creem',
  patreon: 'Patreon',
  dodo: 'Dodo Payments',
  digistore24: 'Digistore24',
  stripe: 'Stripe',
}

export const providerLabel = (key: string): string => PROVIDER_LABELS[key] ?? key

const EMPTY: Record<DeliveryState, number> = {
  delivered: 0,
  skipped: 0,
  scheduled: 0,
  in_flight: 0,
  retrying: 0,
  rejected: 0,
  test: 0,
  needs_you: 0,
}

/** The counts for one provider, zeros when it has no events. */
export const providerCounts = (
  summary: DeliveryHealthSummary | null,
  provider: string,
): Record<DeliveryState, number> => ({ ...EMPTY, ...(summary?.providers[provider] ?? {}) })

export const totalCounts = (summary: DeliveryHealthSummary | null): Record<DeliveryState, number> => ({
  ...EMPTY,
  ...(summary?.counts ?? {}),
})

/**
 * The line under the "needs you" count. One provider names what happened to
 * it; several are listed with their counts.
 *
 *   "Digistore24, 3 of 5 attempts, no retry scheduled"
 *   "Digistore24, 2 deliveries, no retry scheduled"
 *   "Polar 2, Gumroad 1"
 */
export const needsYouLine = (groups: NeedsYouGroup[]): string => {
  const byProvider = new Map<string, NeedsYouGroup>()
  for (const group of groups) {
    const known = byProvider.get(group.provider)
    if (known) {
      byProvider.set(group.provider, { ...known, count: known.count + group.count, attempts: null, max_attempts: null })
    } else {
      byProvider.set(group.provider, { ...group })
    }
  }
  const merged = [...byProvider.values()]
  if (merged.length === 0) return ''
  if (merged.length === 1) {
    const only = merged[0]
    const name = providerLabel(only.provider)
    if (only.count === 1 && only.attempts != null && only.max_attempts != null) {
      return `${name}, ${only.attempts} of ${only.max_attempts} attempts, no retry scheduled`
    }
    return `${name}, ${only.count} deliveries, no retry scheduled`
  }
  return merged
    .sort((a, b) => b.count - a.count)
    .map((group) => `${providerLabel(group.provider)} ${group.count}`)
    .join(', ')
}

export const deliveries = (n: number) => `${n} ${n === 1 ? 'delivery' : 'deliveries'}`

/** The short status of one connected provider, as health lists show it. */
export const providerHealth = (
  counts: Record<DeliveryState, number>,
): { tone: Tone; note: string } => {
  if (counts.needs_you > 0) return { tone: 'bad', note: counts.needs_you === 1 ? 'Needs you' : `${counts.needs_you} need you` }
  if (counts.retrying > 0) return { tone: 'warn', note: `${deliveries(counts.retrying)} retrying` }
  return { tone: 'good', note: 'Connected' }
}

/** The status pill at the top of the dashboard. */
export const overallHealth = (
  summary: DeliveryHealthSummary | null,
): { tone: Tone; text: string } => {
  const counts = totalCounts(summary)
  if (counts.needs_you > 0) {
    return { tone: 'bad', text: `${deliveries(counts.needs_you)} ${counts.needs_you === 1 ? 'needs' : 'need'} you` }
  }
  if (counts.retrying > 0) return { tone: 'warn', text: `${deliveries(counts.retrying)} retrying` }
  return { tone: 'good', text: 'Every purchase reached Ghost' }
}

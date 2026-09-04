// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
/**
 * How healthy webhook delivery is, as the dashboard should describe it.
 *
 * Both the dashboard tile and the connections overview used to count every
 * failed and dead-lettered event ever recorded. Nothing aged out, so once a
 * provider had failed a single delivery during setup it wore a warning
 * forever. A warning that is always on is not a warning: after the sixth amber
 * dot nobody sees the seventh, and that is the one that means something.
 *
 * Two corrections live here. Only recent events count, and a delivery that is
 * still being retried is told apart from one the system has given up on. The
 * first is the difference between a signal and a decoration; the second is the
 * difference between "wait" and "do something".
 */
import type { WebhookEvent } from '../types/api'

/** Long enough to cover a weekend outage, short enough to fall quiet again. */
export const ATTENTION_WINDOW_DAYS = 7

export interface DeliveryHealth {
  /** Failed, but still inside the retry ladder. Usually resolves itself. */
  retrying: number
  /** Attempts exhausted. Nothing happens now unless a human replays it. */
  gaveUp: number
  /** True when somebody has to act, which is the only thing worth a colour. */
  needsAttention: boolean
}

const isRecent = (iso: string, days: number): boolean => {
  const at = Date.parse(iso)
  // An unparseable date is not evidence of a problem, so it drops out rather
  // than counting as recent and lighting the card up for no reason.
  if (Number.isNaN(at)) return false
  return Date.now() - at <= days * 24 * 60 * 60 * 1000
}

/**
 * Classify a set of events for one provider, or for all of them at once.
 */
export const deliveryHealth = (
  events: WebhookEvent[],
  days: number = ATTENTION_WINDOW_DAYS,
): DeliveryHealth => {
  let retrying = 0
  let gaveUp = 0
  for (const event of events) {
    if (!isRecent(event.created_at, days)) continue
    // dead_lettered_at is the honest marker: the status field can say
    // "dead_letter" while the timestamp is what the retry worker actually sets.
    if (event.status === 'dead_letter' || event.dead_lettered_at !== null) gaveUp++
    else if (event.status === 'failed') retrying++
  }
  return { retrying, gaveUp, needsAttention: gaveUp > 0 }
}

/** Group the same classification by provider, for the connections overview. */
export const deliveryHealthByProvider = (
  events: WebhookEvent[],
  days: number = ATTENTION_WINDOW_DAYS,
): Record<string, DeliveryHealth> => {
  const byProvider: Record<string, WebhookEvent[]> = {}
  for (const event of events) {
    ;(byProvider[event.provider] ??= []).push(event)
  }
  const out: Record<string, DeliveryHealth> = {}
  for (const [provider, list] of Object.entries(byProvider)) {
    out[provider] = deliveryHealth(list, days)
  }
  return out
}

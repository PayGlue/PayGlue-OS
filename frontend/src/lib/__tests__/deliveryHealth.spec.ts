// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
import { describe, it, expect } from 'vitest'

import {
  DELIVERY_LABELS,
  DELIVERY_TONES,
  needsYouLine,
  overallHealth,
  providerCounts,
  providerHealth,
} from '../deliveryHealth'
import type { DeliveryHealthSummary, DeliveryState } from '../../types/api'

const counts = (over: Partial<Record<DeliveryState, number>> = {}): Record<DeliveryState, number> => ({
  delivered: 0,
  skipped: 0,
  scheduled: 0,
  in_flight: 0,
  retrying: 0,
  rejected: 0,
  test: 0,
  needs_you: 0,
  ...over,
})

const summary = (over: Partial<DeliveryHealthSummary> = {}): DeliveryHealthSummary => ({
  counts: counts(),
  providers: {},
  needs_you: [],
  ...over,
})

describe('deliveryHealth (PG-402: words only, the backend decides)', () => {
  it('has a word and a tone for every state', () => {
    const states: DeliveryState[] = ['delivered', 'skipped', 'scheduled', 'in_flight', 'retrying', 'rejected', 'test', 'needs_you']
    for (const state of states) {
      expect(DELIVERY_LABELS[state]).toBeTruthy()
      expect(DELIVERY_TONES[state]).toBeTruthy()
    }
    expect(DELIVERY_LABELS.needs_you).toBe('Needs you')
    expect(DELIVERY_TONES.needs_you).toBe('bad')
    expect(DELIVERY_TONES.retrying).toBe('warn')
    // Planned period ends, rejected signatures and test purchases never ask
    // anything of the publisher.
    expect(DELIVERY_TONES.scheduled).toBe('neutral')
    expect(DELIVERY_TONES.rejected).toBe('neutral')
    expect(DELIVERY_TONES.test).toBe('neutral')
  })

  it('names one stuck delivery by its attempts', () => {
    expect(
      needsYouLine([{ provider: 'digistore24', count: 1, attempts: 3, max_attempts: 5, latest_at: '' }]),
    ).toBe('Digistore24, 3 of 5 attempts, no retry scheduled')
  })

  it('lists several providers with their counts, largest first', () => {
    expect(
      needsYouLine([
        { provider: 'gumroad', count: 1, attempts: 2, max_attempts: 5, latest_at: '' },
        { provider: 'polar', count: 2, attempts: null, max_attempts: null, latest_at: '' },
      ]),
    ).toBe('Polar 2, Gumroad 1')
  })

  it('folds the same provider of several tenants into one', () => {
    expect(
      needsYouLine([
        { provider: 'polar', count: 1, attempts: 2, max_attempts: 5, latest_at: '' },
        { provider: 'polar', count: 1, attempts: 5, max_attempts: 5, latest_at: '' },
      ]),
    ).toBe('Polar, 2 deliveries, no retry scheduled')
  })

  it('says the same thing in the pill as in the card and the health list', () => {
    const stuck = summary({
      counts: counts({ needs_you: 1, delivered: 9 }),
      providers: { digistore24: counts({ needs_you: 1 }) },
    })
    expect(overallHealth(stuck)).toEqual({ tone: 'bad', text: '1 delivery needs you' })
    expect(providerHealth(providerCounts(stuck, 'digistore24'))).toEqual({ tone: 'bad', note: 'Needs you' })
    expect(providerHealth(providerCounts(stuck, 'polar'))).toEqual({ tone: 'good', note: 'Connected' })

    const retrying = summary({ counts: counts({ retrying: 2 }), providers: { polar: counts({ retrying: 2 }) } })
    expect(overallHealth(retrying)).toEqual({ tone: 'warn', text: '2 deliveries retrying' })
    expect(providerHealth(providerCounts(retrying, 'polar')).note).toBe('2 deliveries retrying')

    expect(overallHealth(summary({ counts: counts({ scheduled: 3, rejected: 1, test: 1 }) }))).toEqual({
      tone: 'good',
      text: 'Every purchase reached Ghost',
    })
  })

  it('treats a missing summary as healthy, not as an error', () => {
    expect(overallHealth(null).tone).toBe('good')
    expect(providerCounts(null, 'polar').needs_you).toBe(0)
  })
})

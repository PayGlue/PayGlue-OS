// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
import { describe, it, expect } from 'vitest'

import { deliveryHealth, deliveryHealthByProvider } from '../deliveryHealth'
import type { WebhookEvent } from '../../types/api'

const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString()

const event = (over: Partial<WebhookEvent>): WebhookEvent =>
  ({
    id: 1,
    tenant_slug: 'acme',
    provider: 'polar',
    status: 'processed',
    attempts: 0,
    next_attempt_at: null,
    last_error: '',
    endpoint_path: '',
    endpoint_metadata: {},
    payload_snapshot: {},
    headers_snapshot: {},
    created_at: daysAgo(1),
    updated_at: daysAgo(1),
    dead_lettered_at: null,
    ...over,
  }) as WebhookEvent

describe('deliveryHealth', () => {
  it('ignores failures older than the window', () => {
    // The whole point of PG-264. A webhook that failed once during setup in
    // June kept the card amber for good, because nothing ever aged out.
    const health = deliveryHealth([
      event({ status: 'dead_letter', dead_lettered_at: daysAgo(40), created_at: daysAgo(40) }),
      event({ status: 'failed', created_at: daysAgo(30) }),
    ])
    expect(health).toEqual({ retrying: 0, gaveUp: 0, needsAttention: false })
  })

  it('tells a retry apart from a give-up', () => {
    const health = deliveryHealth([
      event({ status: 'failed' }),
      event({ status: 'dead_letter', dead_lettered_at: daysAgo(1) }),
    ])
    expect(health.retrying).toBe(1)
    expect(health.gaveUp).toBe(1)
  })

  it('asks for attention only when nobody will retry', () => {
    // A delivery still in the ladder resolves itself, so it is worth showing
    // and not worth a colour.
    expect(deliveryHealth([event({ status: 'failed' })]).needsAttention).toBe(false)
    expect(
      deliveryHealth([event({ status: 'dead_letter', dead_lettered_at: daysAgo(1) })])
        .needsAttention,
    ).toBe(true)
  })

  it('trusts the dead-letter timestamp even when the status lags', () => {
    const health = deliveryHealth([event({ status: 'failed', dead_lettered_at: daysAgo(1) })])
    expect(health).toEqual({ retrying: 0, gaveUp: 1, needsAttention: true })
  })

  it('leaves successful and skipped deliveries out of it', () => {
    const health = deliveryHealth([
      event({ status: 'processed' }),
      event({ status: 'skipped' }),
      event({ status: 'received' }),
    ])
    expect(health).toEqual({ retrying: 0, gaveUp: 0, needsAttention: false })
  })

  it('drops an unreadable date instead of counting it as recent', () => {
    // An unparseable timestamp is not evidence of a problem, and defaulting it
    // into the window would light the card up for nothing.
    const health = deliveryHealth([event({ status: 'dead_letter', created_at: 'not a date' })])
    expect(health.gaveUp).toBe(0)
  })

  it('keeps one provider out of another provider count', () => {
    const byProvider = deliveryHealthByProvider([
      event({ provider: 'polar', status: 'dead_letter', dead_lettered_at: daysAgo(1) }),
      event({ provider: 'paddle', status: 'failed' }),
    ])
    expect(byProvider.polar.needsAttention).toBe(true)
    expect(byProvider.paddle.needsAttention).toBe(false)
    expect(byProvider.paddle.retrying).toBe(1)
  })
})

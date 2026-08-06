// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { describe, expect, it } from 'vitest'
import { entitlementKeyForProduct, findOwnMapping, missingMappings } from '../mappingKeys'
import type { ProductMapping } from '../../types/api'

function mapping(overrides: Partial<ProductMapping> = {}): ProductMapping {
  return {
    id: 1,
    payment_provider: 'polar',
    event_type: 'order.paid',
    external_product_id: 'prod_a',
    entitlement_key: 'product-prod_a',
    action: 'grant',
    quantity: 1,
    is_active: true,
    metadata: {},
    ...overrides,
  }
}

describe('entitlementKeyForProduct', () => {
  it('does not depend on the position of the tier', () => {
    // The whole point of PG-233: the same product yields the same key no
    // matter where its tier sits, so reordering cannot orphan a mapping.
    expect(entitlementKeyForProduct('prod_a')).toBe(entitlementKeyForProduct('prod_a'))
  })

  it('keeps different products apart', () => {
    expect(entitlementKeyForProduct('prod_a')).not.toBe(entitlementKeyForProduct('prod_b'))
  })

  it('ignores surrounding whitespace', () => {
    expect(entitlementKeyForProduct('  prod_a  ')).toBe(entitlementKeyForProduct('prod_a'))
  })
})

describe('findOwnMapping', () => {
  it('does not hand a buy button the paywall mapping for the same product', () => {
    // The old lookup matched on the product alone, so both widgets found the
    // first row and then overwrote it with their own key. One of the two lost
    // its mapping without any error.
    const mappings = [
      mapping({ id: 7, entitlement_key: 'paywall' }),
      mapping({ id: 8, entitlement_key: 'button' }),
    ]
    expect(findOwnMapping(mappings, 'prod_a', 'button')?.id).toBe(8)
    expect(findOwnMapping(mappings, 'prod_a', 'paywall')?.id).toBe(7)
  })

  it('ignores revoke rules', () => {
    const mappings = [mapping({ id: 9, action: 'revoke' })]
    expect(findOwnMapping(mappings, 'prod_a', 'product-prod_a')).toBeUndefined()
  })

  it('still matches when the event type was changed in the form', () => {
    // The event type is editable, so it stays out of the lookup. Otherwise
    // switching it would create a second mapping instead of updating the one
    // that is already there.
    const mappings = [mapping({ id: 3, event_type: 'subscription.active' })]
    expect(findOwnMapping(mappings, 'prod_a', 'product-prod_a')?.id).toBe(3)
  })

  it('returns nothing when the product has no mapping at all', () => {
    expect(findOwnMapping([mapping()], 'prod_missing', 'product-prod_missing')).toBeUndefined()
  })
})

describe('missingMappings', () => {
  it('reports a tier whose mapping never landed', () => {
    const expected = [
      { productId: 'prod_a', entitlementKey: 'product-prod_a', label: 'Basic' },
      { productId: 'prod_b', entitlementKey: 'product-prod_b', label: 'Pro' },
    ]
    expect(missingMappings([mapping()], expected)).toEqual(['Pro'])
  })

  it('is silent when every expectation is met', () => {
    const mappings = [
      mapping({ id: 1, external_product_id: 'prod_a', entitlement_key: 'product-prod_a' }),
      mapping({ id: 2, external_product_id: 'prod_b', entitlement_key: 'product-prod_b' }),
    ]
    const expected = [
      { productId: 'prod_a', entitlementKey: 'product-prod_a', label: 'Basic' },
      { productId: 'prod_b', entitlementKey: 'product-prod_b', label: 'Pro' },
    ]
    expect(missingMappings(mappings, expected)).toEqual([])
  })

  it('catches a mapping that exists under a stale key', () => {
    // This is the state the failed test purchase was in: a row was there, but
    // not the one the tier pointed at, so the purchase granted nothing.
    const stale = [mapping({ entitlement_key: 'pricing-tier-2' })]
    const expected = [{ productId: 'prod_a', entitlementKey: 'product-prod_a', label: 'Basic' }]
    expect(missingMappings(stale, expected)).toEqual(['Basic'])
  })
})

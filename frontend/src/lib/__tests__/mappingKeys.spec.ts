// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// Finding the rule that says what buying a product does (PG-254).
//
// These used to test a lookup on `(product, entitlement_key)` and a
// post-condition that checked afterwards whether a rule had appeared. Both are
// gone: the rule is written server-side in the same transaction as the widget,
// so it cannot be missing, and the key is no longer part of a rule's identity.
//
// What is worth pinning is the mistake that would silently cost a customer
// their settings: looking up by key would not find a rule named `pro`, the
// editor would show its defaults, and the next save would write those defaults
// over what they had configured.

import { describe, expect, it } from 'vitest'
import { entitlementKeyForProduct, ruleForProduct } from '../mappingKeys'
import type { ProductMapping } from '../../types/api'

const mapping = (over: Partial<ProductMapping> = {}): ProductMapping =>
  ({
    id: 1,
    payment_provider: 'polar',
    event_type: 'order.paid',
    external_product_id: 'prod_a',
    entitlement_key: 'product-prod_a',
    action: 'grant',
    quantity: 1,
    is_active: true,
    metadata: {},
    ...over,
  }) as ProductMapping

describe('entitlementKeyForProduct', () => {
  it('is stable for a product', () => {
    expect(entitlementKeyForProduct('prod_a')).toBe(entitlementKeyForProduct('prod_a'))
  })

  it('differs between products', () => {
    expect(entitlementKeyForProduct('prod_a')).not.toBe(entitlementKeyForProduct('prod_b'))
  })

  it('ignores surrounding whitespace', () => {
    expect(entitlementKeyForProduct('  prod_a  ')).toBe(entitlementKeyForProduct('prod_a'))
  })
})

describe('ruleForProduct', () => {
  it('finds the rule whatever it happens to be called', () => {
    // The case that matters for existing installations. Keys in use are words
    // like `pro` and `founding_member`, written long before any of this.
    const rules = [mapping({ id: 4, entitlement_key: 'pro' })]

    expect(ruleForProduct(rules, 'polar', 'prod_a')?.id).toBe(4)
  })

  it('finds the one a buy button created when a pricing tier asks', () => {
    // Both widgets offer the same product, and there is one rule between them.
    const rules = [mapping({ id: 5, entitlement_key: 'button' })]

    expect(ruleForProduct(rules, 'polar', 'prod_a')?.id).toBe(5)
  })

  it('keeps two providers apart even on the same product id', () => {
    const rules = [
      mapping({ id: 6, payment_provider: 'polar' }),
      mapping({ id: 7, payment_provider: 'gumroad' }),
    ]

    expect(ruleForProduct(rules, 'gumroad', 'prod_a')?.id).toBe(7)
  })

  it('ignores a revoke rule, which answers a cancellation rather than a sale', () => {
    const rules = [mapping({ id: 8, action: 'revoke' })]

    expect(ruleForProduct(rules, 'polar', 'prod_a')).toBeUndefined()
  })

  it('returns nothing for a product that has no rule yet', () => {
    expect(ruleForProduct([mapping()], 'polar', 'prod_missing')).toBeUndefined()
  })

  it('returns nothing when no product has been picked', () => {
    expect(ruleForProduct([mapping()], 'polar', '')).toBeUndefined()
  })
})

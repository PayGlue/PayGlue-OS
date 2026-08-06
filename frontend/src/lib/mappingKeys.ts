import type { ProductMapping } from '../types/api'

/**
 * PG-233. Two rules that have to agree with each other, and with the database.
 *
 * `ProductMapping` carries a unique constraint over six fields, of which the
 * editors control four: provider, event type, product id and entitlement key.
 * Everything below exists so that the key we write and the mapping we look up
 * are derived from the same facts as that constraint.
 */

/**
 * The entitlement key of a pricing tier used to be `pricing-tier-${index + 1}`.
 * That tied it to a position: reorder or delete a tier and the key moved onto a
 * different product, the old tier's mapping stayed behind under the orphaned
 * key, and the tier that inherited the position collided with it. Deriving the
 * key from the product instead makes it survive any reordering, and a tier
 * without a product has no mapping to key in the first place.
 */
export function entitlementKeyForProduct(productId: string): string {
  return `product-${productId.trim()}`
}

/**
 * The key a widget with a fixed entitlement writes. Buy buttons and paywalls
 * are not positional, so they keep their historical keys.
 */
export type FixedEntitlementKey = 'button' | 'paywall'

/**
 * Find the mapping a widget owns for a product.
 *
 * Matching on the product id alone was the second half of the bug: a buy button
 * and a paywall pointing at the same product both found whichever mapping came
 * first and then overwrote it with their own entitlement key, so one of the two
 * silently lost its mapping. The key belongs in the lookup because it is part
 * of the constraint.
 *
 * The event type deliberately stays out. It is editable in the form, and
 * matching on it would make a changed event type create a second mapping
 * instead of updating the existing one.
 */
export function findOwnMapping(
  mappings: readonly ProductMapping[],
  productId: string,
  entitlementKey: string,
): ProductMapping | undefined {
  return mappings.find(
    m =>
      m.external_product_id === productId &&
      m.entitlement_key === entitlementKey &&
      m.action === 'grant',
  )
}

export type MappingExpectation = { productId: string; entitlementKey: string; label: string }

/**
 * Post-condition after saving.
 *
 * Reporting the error from the create call only covers the case where the call
 * throws. It does not establish that a mapping exists at the end, which is the
 * thing that actually matters: a widget saved without one takes money and
 * grants nothing, and the event log calls that "processed". Blocking the save
 * would have been the wrong shape, because the mapping is built from defaults
 * rather than from user input, so there is no missing field to insist on.
 *
 * Returns the labels of everything that should have a mapping and does not.
 */
export function missingMappings(
  mappings: readonly ProductMapping[],
  expected: readonly MappingExpectation[],
): string[] {
  return expected
    .filter(e => !findOwnMapping(mappings, e.productId, e.entitlementKey))
    .map(e => e.label)
}

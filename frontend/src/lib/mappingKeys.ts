import type { ProductMapping } from '../types/api'

/**
 * Finding the one rule that says what buying a product does.
 *
 * ## What changed, and why the lookup no longer mentions the key
 *
 * These helpers used to search on `(product, entitlement_key)`, because the key
 * was part of the unique constraint and each editor wrote its own: a buy button
 * wrote `button`, a paywall `paywall`, a pricing tier `product-<id>`. One
 * product could therefore hold three rules that disagreed with each other, and
 * a purchase applied all of them (PG-254).
 *
 * Since then the key is out of the constraint. There is exactly one rule per
 * product, and its name is whatever it was created with, which for existing
 * installations is words like `pro` or `founding_member`.
 *
 * Keeping the key in the lookup would now be actively harmful. A buy button
 * asking for the rule under the name `button` would not find the one named
 * `pro`, would show its defaults instead of what is actually configured, and
 * would write those defaults over the real settings on the next save. So the
 * lookup asks what the constraint asks: which product, from which provider.
 */

/** The name a rule gets when a pricing tier is the first thing to create it. */
export function entitlementKeyForProduct(productId: string): string {
  return `product-${productId.trim()}`
}

/**
 * The rule for a product, or undefined if nothing grants it yet.
 *
 * The provider belongs in here because it is part of the identity: the same
 * product id string could in principle exist at two providers, and those are
 * two different things to sell.
 */
export function ruleForProduct(
  mappings: readonly ProductMapping[],
  provider: string,
  productId: string,
): ProductMapping | undefined {
  if (!productId) return undefined
  return mappings.find(
    m =>
      m.external_product_id === productId &&
      m.payment_provider === provider &&
      m.action === 'grant',
  )
}

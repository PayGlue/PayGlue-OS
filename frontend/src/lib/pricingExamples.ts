// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

// Example values for a new pricing table. They show as grey placeholders in the
// form and fill the empty fields of the preview, so a fresh table never looks
// broken. They are never saved: only what the user types goes to the server.
import type { PricingFeatureIcon } from '../types/api'

export interface TierExample {
  name: string
  description: string
  price: string
  features: string[]
}

export const TIER_EXAMPLES: TierExample[] = [
  { name: 'Free', description: 'For every reader', price: '0', features: ['Weekly newsletter', 'All public posts'] },
  { name: 'Supporter', description: 'For regular readers', price: '5', features: ['Every post and the full archive', 'Members-only newsletter'] },
  { name: 'Patron', description: 'For your biggest fans', price: '12', features: ['Everything in Supporter', 'Early access to new posts'] },
]

export function tierExample(index: number): TierExample {
  return TIER_EXAMPLES[Math.min(index, TIER_EXAMPLES.length - 1)]
}

interface PreviewTierFields {
  name: string
  description: string
  price_monthly: string
  price_yearly: string
  features: { text: string; icon: PricingFeatureIcon }[]
}

/** Fill the empty fields of one preview tier with the example for its position. */
export function withExample<T extends PreviewTierFields>(tier: T, index: number): T {
  const ex = tierExample(index)
  const yearly = ex.price === '0' ? '0' : String(Number(ex.price) * 10)
  return {
    ...tier,
    name: tier.name || ex.name,
    description: tier.description || ex.description,
    price_monthly: tier.price_monthly || ex.price,
    price_yearly: tier.price_yearly || yearly,
    features: tier.features.some(f => f.text.trim())
      ? tier.features
      : ex.features.map(text => ({ text, icon: 'check' as PricingFeatureIcon })),
  }
}

/** Positions (1-based) of tiers that still have no name, for the save check. */
export function unnamedTiers(tiers: { name: string }[]): number[] {
  return tiers.flatMap((t, i) => (t.name.trim() ? [] : [i + 1]))
}

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { computed, onMounted, reactive, ref } from 'vue'
import { supabase } from '../lib/supabase'

/**
 * The founding-member ladder, live from `pricing_tiers`.
 *
 * Extracted from the landing page when /founding was added, rather than copied. Two
 * pages quoting a price from two places is the kind of drift nobody notices
 * until a buyer sees one number on the landing page and another at checkout.
 * Whatever the ladder does, both pages now do the same thing at the same time.
 *
 * PG-206: the tier price used to be a one-time entry fee, with a separate
 * locked monthly rate per tier. Creem cannot combine a one-off fee with a
 * subscription, so every one-time buyer would have had to run a second
 * checkout at launch to keep their rate. The ladder is now plain monthly
 * subscription pricing: **the tier price IS the rate**, from day one, and it
 * never rises. No conversion, no cliff, and one number instead of two.
 */

/**
 * Keyed by the `tier` column in pricing_tiers, NOT by price.
 *
 * It used to be keyed by price, and the PG-206 repricing (9/19/29/39/49 ->
 * 9/14/19/24/29) turned that into a live sales bug waiting for the first ten
 * spots to sell: at 14 and 24 euro no entry existed, so `checkoutUrl` went
 * empty and the button disappeared entirely, while 19 and 29 euro silently
 * resolved to the tier-2 and tier-3 products, i.e. the wrong price. Exactly
 * the failure the old comment here warned about, reintroduced from the other
 * direction.
 *
 * A tier number is stable; a price is not. Never key this by price again.
 */
const CHECKOUT_URLS: Record<number, string> = {
  1: import.meta.env.VITE_CREEM_CHECKOUT_TIER1 as string,
  2: import.meta.env.VITE_CREEM_CHECKOUT_TIER2 as string,
  3: import.meta.env.VITE_CREEM_CHECKOUT_TIER3 as string,
  4: import.meta.env.VITE_CREEM_CHECKOUT_TIER4 as string,
  5: import.meta.env.VITE_CREEM_CHECKOUT_TIER5 as string,
}

/**
 * Copy per step. Prices deliberately live in the database only -- hardcoding
 * them here is what drifted last time.
 */
const TIER_LABELS: Record<number, string> = {
  1: 'First 10',
  2: 'Next 10',
  3: 'Next 10',
  4: 'Next 10',
  // Not "After that": all five steps are batches of ten. That wording is left
  // over from the old ladder, where the last step was the resting price
  // everyone paid from then on. The founding offer now simply ends after 50.
  5: 'Next 10',
}

export const AGENCY_MONTHLY = 59
export const AGENCY_ANNUAL = 590

export function useFoundingTier() {
  // Pre-hydration guess only; loadActiveTier() replaces the whole ladder from
  // pricing_tiers a moment later. It must match the real starting state, or the
  // ladder flashes wrong numbers before settling.
  const pricingTiers = reactive([
    { tier: 1, price: 9, spots: 10, label: 'First 10', status: 'current' },
    { tier: 2, price: 14, spots: 10, label: 'Next 10', status: 'upcoming' },
    { tier: 3, price: 19, spots: 10, label: 'Next 10', status: 'upcoming' },
    { tier: 4, price: 24, spots: 10, label: 'Next 10', status: 'upcoming' },
    { tier: 5, price: 29, spots: 10 as number | null, label: 'Next 10', status: 'upcoming' },
  ])

  const currentTier = ref(1)
  const currentTierPrice = ref(9)
  const spotsLeft = ref(10)

  const currentTierIndex = computed(() => currentTier.value)
  const checkoutEnabled = import.meta.env.VITE_ENABLE_CHECKOUT === 'true'
  // By tier, never by price. See the CHECKOUT_URLS comment above.
  const checkoutUrl = computed(() => CHECKOUT_URLS[currentTier.value] ?? '')

  const fmt = (value: number) => `${value} €`

  /**
   * Loads the whole ladder, not just the active step.
   *
   * The displayed prices used to be hardcoded above while only the active one
   * came from the database, so a repricing left the roadmap showing numbers
   * nobody could buy at. The table is the single source of truth now: every
   * price and spot count on screen comes from it, and the array above is only
   * what shows for the fraction of a second before this resolves.
   */
  async function loadActiveTier() {
    const { data } = await supabase
      .from('pricing_tiers')
      .select('tier, price_eur, spots_total, spots_sold, active')
      .order('tier')
    if (!data?.length) return

    const active = data.find((t) => t.active)
    if (active) {
      currentTier.value = active.tier
      currentTierPrice.value = Math.round(active.price_eur / 100)
      spotsLeft.value = active.spots_total - active.spots_sold
    }

    pricingTiers.splice(
      0,
      pricingTiers.length,
      ...data.map((t) => ({
        tier: t.tier,
        price: Math.round(t.price_eur / 100),
        spots: t.spots_total as number | null,
        label: TIER_LABELS[t.tier] ?? `Tier ${t.tier}`,
        // Ordering by tier, not by price: a step is sold out because it came
        // earlier, not because it happens to be cheaper.
        status:
          active && t.tier === active.tier
            ? 'current'
            : active && t.tier < active.tier
              ? 'sold'
              : 'upcoming',
      })),
    )
  }

  /** Opt-in so a caller that only needs the numbers does not open a socket. */
  function subscribeToTierChanges() {
    supabase
      .channel('pricing_tiers_changes')
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'pricing_tiers' },
        () => {
          loadActiveTier()
        },
      )
      .subscribe()
  }

  onMounted(loadActiveTier)

  return {
    pricingTiers,
    currentTier,
    currentTierPrice,
    currentTierIndex,
    spotsLeft,
    checkoutEnabled,
    checkoutUrl,
    fmt,
    loadActiveTier,
    subscribeToTierChanges,
  }
}

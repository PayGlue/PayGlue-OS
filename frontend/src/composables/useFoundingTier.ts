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
 * TIERn matches the `tier` column in the pricing_tiers table: tier 1 is the
 * 9 euro entry step. Do NOT renumber these to a 0-based index -- that was the
 * old naming and it silently pointed the 29 euro step at the 19 euro product.
 */
const CHECKOUT_URLS: Record<number, string> = {
  9: import.meta.env.VITE_CREEM_CHECKOUT_TIER1 as string,
  19: import.meta.env.VITE_CREEM_CHECKOUT_TIER2 as string,
  29: import.meta.env.VITE_CREEM_CHECKOUT_TIER3 as string,
  39: import.meta.env.VITE_CREEM_CHECKOUT_TIER4 as string,
  49: import.meta.env.VITE_CREEM_CHECKOUT_TIER5 as string,
}

export const AGENCY_MONTHLY = 59
export const AGENCY_ANNUAL = 590

export function useFoundingTier() {
  // Statuses here are only the pre-hydration guess; loadActiveTier() overwrites
  // them from the pricing_tiers table a moment later. They must match the real
  // starting state, otherwise the ladder flashes a wrong "sold out" first.
  const pricingTiers = reactive([
    { price: 9, spots: 10, label: 'First 10', status: 'current' },
    { price: 19, spots: 10, label: 'Next 10', status: 'upcoming' },
    { price: 29, spots: 10, label: 'Next 10', status: 'upcoming' },
    { price: 39, spots: 10, label: 'Next 10', status: 'upcoming' },
    { price: 49, spots: null as number | null, label: 'After that', status: 'upcoming' },
  ])

  const currentTierPrice = ref(9)
  const spotsLeft = ref(10)

  const currentTierIndex = computed(() => pricingTiers.findIndex((t) => t.status === 'current') + 1)
  const checkoutEnabled = import.meta.env.VITE_ENABLE_CHECKOUT === 'true'
  const checkoutUrl = computed(() => CHECKOUT_URLS[currentTierPrice.value] ?? '')

  const fmt = (value: number) => `${value} €`

  async function loadActiveTier() {
    const { data } = await supabase
      .from('pricing_tiers')
      .select('tier, price_eur, spots_total, spots_sold')
      .eq('active', true)
      .single()
    if (data) {
      currentTierPrice.value = Math.round(data.price_eur / 100)
      spotsLeft.value = data.spots_total - data.spots_sold
      pricingTiers.forEach((t) => {
        if (t.price === currentTierPrice.value) t.status = 'current'
        else if (t.price < currentTierPrice.value) t.status = 'sold'
        else t.status = 'upcoming'
      })
    }
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

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { describe, expect, it } from 'vitest'
import { tierExample, unnamedTiers, withExample } from '../pricingExamples'

import type { PricingFeatureIcon } from '../../types/api'

const empty = { name: '', description: '', price_monthly: '', price_yearly: '', features: [] as { text: string; icon: PricingFeatureIcon }[] }

describe('pricing table examples', () => {
  it('fills every empty field of a fresh tier', () => {
    const t = withExample(empty, 1)
    expect(t.name).toBe('Supporter')
    expect(t.description).toBe('For regular readers')
    expect(t.price_monthly).toBe('5')
    expect(t.price_yearly).toBe('50')
    expect(t.features.map(f => f.text)).toEqual(['Every post and the full archive', 'Members-only newsletter'])
  })

  it('never overrides what the user typed', () => {
    const typed = { ...empty, name: 'Gold', price_monthly: '9', features: [{ text: 'Podcast', icon: 'dot' as const }] }
    const t = withExample(typed, 0)
    expect(t.name).toBe('Gold')
    expect(t.price_monthly).toBe('9')
    expect(t.features).toEqual([{ text: 'Podcast', icon: 'dot' }])
    expect(t.description).toBe('For every reader')
  })

  it('reuses the last example past the third tier', () => {
    expect(tierExample(5).name).toBe('Patron')
  })

  it('lists tiers without a name', () => {
    expect(unnamedTiers([{ name: 'Free' }, { name: ' ' }, { name: '' }])).toEqual([2, 3])
  })
})

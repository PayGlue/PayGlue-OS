// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
import { ApiHttpError } from './api'

export const PLAN_ORDER = ['solo', 'studio', 'agency'] as const
export type UpgradablePlanKey = (typeof PLAN_ORDER)[number]

const PLAN_NAMES: Record<string, string> = {
  solo: 'Solo',
  studio: 'Studio',
  agency: 'Agency',
  founding: 'Founding Member',
}

export const planDisplayName = (key: string | null | undefined): string =>
  (key && PLAN_NAMES[key]) || 'your plan'

export type PlanTier = {
  key: UpgradablePlanKey
  name: string
  tagline: string
  monthly: number
  annual: number
  features: string[]
}

// Shared by the landing page's public pricing section and the in-dashboard
// Plans page (PG-150) -- same tiers, same numbers, one source of truth.
export const PLAN_TIERS: PlanTier[] = [
  {
    key: 'solo',
    name: 'Solo',
    tagline: 'One publication, done right',
    monthly: 19,
    annual: 190,
    features: [
      '1 publication',
      '1 buy button',
      '1 paywall',
      '1 pricing table',
      '2 payment providers',
      '1 team member',
      '1,000 webhook events/mo',
      'Ghost member sync, always up to date',
    ],
  },
  {
    key: 'studio',
    name: 'Studio',
    tagline: 'For growing publishers',
    monthly: 39,
    annual: 390,
    features: [
      'Up to 3 publications',
      '5 buy buttons per publication',
      '3 paywalls per publication',
      '3 pricing tables per publication',
      '4 payment providers',
      '3 team members',
      '10,000 webhook events/mo',
      'Ghost member sync, always up to date',
    ],
  },
  {
    key: 'agency',
    name: 'Agency',
    tagline: 'For teams and networks',
    monthly: 59,
    annual: 590,
    features: [
      'Unlimited publications',
      'Unlimited buy buttons',
      'Unlimited paywalls',
      'Unlimited pricing tables',
      'All available payment providers',
      'Unlimited team members',
      'Unlimited webhook events',
      'Ghost member sync, always up to date',
      'Personal onboarding',
      'One-on-one call with founder',
    ],
  },
]

/** True if `error` is a 402 plan-limit response from the backend (see PlanLimitExceededError). */
export const isPlanLimitError = (error: unknown): error is ApiHttpError =>
  error instanceof ApiHttpError && error.status === 402

/** The plan key the backend reported the user was on when a 402 fired, if present. */
export const planKeyFromError = (error: unknown): string | null => {
  if (!(error instanceof ApiHttpError)) return null
  const plan = error.data?.plan
  return typeof plan === 'string' ? plan : null
}

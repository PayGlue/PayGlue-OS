// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// HAND-MAINTAINED in the OSS repo -- the sync script never overwrites this
// file (see scripts/sync-oss.sh NEVER_SYNC_PATHS in the private repo). It is
// the private router minus every marketing/legal route and the dual-domain
// redirect logic. When the private repo gains a dashboard route, port it here
// by hand as part of the next release.

import { createRouter, createWebHistory } from 'vue-router'
import type { RouteLocationNormalized } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { supabase } from '../lib/supabase'

const LoginView = () => import('../views/LoginView.vue')
const SignupView = () => import('../views/SignupView.vue')
const DashboardEntryView = () => import('../views/DashboardEntryView.vue')
const TenantSelectView = () => import('../views/TenantSelectView.vue')
const TenantOnboardingView = () => import('../views/TenantOnboardingView.vue')
const TenantPausedView = () => import('../views/TenantPausedView.vue')
const DashboardView = () => import('../views/DashboardView.vue')
const InstallationView = () => import('../views/InstallationView.vue')
const PaywallConfigView = () => import('../views/PaywallConfigView.vue')
const BuyButtonView = () => import('../views/BuyButtonView.vue')

const MappingsView = () => import('../views/MappingsView.vue')
const TeamView = () => import('../views/TeamView.vue')
const PricingTableView = () => import('../views/PricingTableView.vue')

const EventsView = () => import('../views/EventsView.vue')
const BillingView = () => import('../views/BillingView.vue')
const PlansView = () => import('../views/PlansView.vue')
const PreferencesView = () => import('../views/PreferencesView.vue')
const AffiliateView = () => import('../views/AffiliateView.vue')
const OnboardingThankYouView = () => import('../views/OnboardingThankYouView.vue')
const ConnectionsOverviewView = () => import('../views/ConnectionsOverviewView.vue')
const ConnectionGhostView = () => import('../views/ConnectionGhostView.vue')
// The 8 payment providers now share one config-driven detail view.
const ConnectionDetailView = () => import('../views/ConnectionDetailView.vue')
const ConnectionStripeView = () => import('../views/ConnectionStripeView.vue')
const OrganizationView = () => import('../views/OrganizationView.vue')
const SupportView = () => import('../views/SupportView.vue')
const AuthCallbackView = () => import('../views/AuthCallbackView.vue')
const AuthMfaChallengeView = () => import('../views/AuthMfaChallengeView.vue')
const ResetPasswordView = () => import('../views/ResetPasswordView.vue')
const AuthResetView = () => import('../views/AuthResetView.vue')
const WelcomeView = () => import('../views/WelcomeView.vue')

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    // Only scroll to a hash that actually exists. Old posts and emails carry
    // anchors for sections that have since been removed, and Vue Router warns
    // (and does nothing) for those -- landing at the top is the better answer.
    if (to.hash && typeof document !== 'undefined' && document.querySelector(to.hash)) {
      return { el: to.hash, behavior: 'smooth' }
    }
    return { top: 0 }
  },
  routes: [
    // The OSS app is the dashboard only -- there is no landing page here.
    {
      path: '/',
      redirect: { name: 'dashboard-entry' },
    },
    {
      path: '/auth/callback',
      name: 'auth-callback',
      component: AuthCallbackView,
    },
    {
      path: '/auth/mfa',
      name: 'auth-mfa-challenge',
      component: AuthMfaChallengeView,
    },
    {
      path: '/auth/reset',
      name: 'auth-reset',
      component: AuthResetView,
      // PG-186: this view only ever calls supabase.auth.getSession()/
      // updateUser() directly -- it never touches the Pinia session store.
      // Letting the guard's session.bootstrap() run here anyway raced a
      // fresh recovery session against our own backend session-sync call;
      // any failure there (bootstrap()'s catch-all) signed the user back
      // out before this view could read the session it just got from
      // verifyOtp(), producing a misleading "invalid or expired" error on
      // a code that had, in fact, just worked.
      meta: { skipBootstrap: true },
    },
    {
      path: '/reset-password',
      name: 'reset-password',
      component: ResetPasswordView,
    },
    {
      path: '/welcome',
      name: 'welcome',
      component: WelcomeView,
    },
    {
      path: '/login',
      name: 'login',
      component: LoginView,
    },
    {
      path: '/signup',
      name: 'signup',
      component: SignupView,
    },
    {
      path: '/dashboard',
      name: 'dashboard-entry',
      component: DashboardEntryView,
    },
    {
      path: '/tenant/select',
      name: 'tenant-select',
      component: TenantSelectView,
      meta: { requiresAuth: true },
    },
    {
      path: '/tenant/create',
      name: 'tenant-onboarding',
      component: TenantOnboardingView,
      meta: { requiresAuth: true },
    },
    {
      path: '/t/:tenantSlug/onboarding',
      name: 'tenant-onboarding-preview',
      component: TenantOnboardingView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug',
      redirect: (to) => ({
        name: 'dashboard',
        params: { tenantSlug: String(to.params.tenantSlug ?? '') },
      }),
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/dashboard',
      name: 'dashboard',
      component: DashboardView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/paused',
      name: 'tenant-paused',
      component: TenantPausedView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connect',
      redirect: (to) => `/t/${to.params.tenantSlug}/integrations`,
    },
    {
      path: '/t/:tenantSlug/installation',
      name: 'installation',
      component: InstallationView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/paywall',
      name: 'paywall-config',
      component: PaywallConfigView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/buttons',
      name: 'buy-buttons',
      component: BuyButtonView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/mappings',
      name: 'mappings',
      component: MappingsView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/team',
      name: 'team',
      component: TeamView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/pricing',
      name: 'pricing',
      component: PricingTableView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/integrations',
      redirect: (to) => `/t/${to.params.tenantSlug}/connections`,
    },
    {
      path: '/t/:tenantSlug/connections',
      name: 'connections-overview',
      component: ConnectionsOverviewView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/ghost',
      name: 'connection-ghost',
      component: ConnectionGhostView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/stripe',
      name: 'connection-stripe',
      component: ConnectionStripeView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    // Every payment provider shares the generic detail view; the provider key
    // is passed as a prop and validated below (unknown keys 404 via the guard).
    {
      path: '/t/:tenantSlug/connection/polar',
      name: 'connection-polar',
      component: ConnectionDetailView,
      props: { provider: 'polar' },
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/lemonsqueezy',
      name: 'connection-lemonsqueezy',
      component: ConnectionDetailView,
      props: { provider: 'lemonsqueezy' },
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/paypal',
      name: 'connection-paypal',
      component: ConnectionDetailView,
      props: { provider: 'paypal' },
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/gumroad',
      name: 'connection-gumroad',
      component: ConnectionDetailView,
      props: { provider: 'gumroad' },
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/paddle',
      name: 'connection-paddle',
      component: ConnectionDetailView,
      props: { provider: 'paddle' },
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/kofi',
      name: 'connection-kofi',
      component: ConnectionDetailView,
      props: { provider: 'kofi' },
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/creem',
      name: 'connection-creem',
      component: ConnectionDetailView,
      props: { provider: 'creem' },
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/patreon',
      name: 'connection-patreon',
      component: ConnectionDetailView,
      props: { provider: 'patreon' },
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/organization',
      name: 'organization',
      component: OrganizationView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/support',
      name: 'support',
      component: SupportView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/events',
      name: 'events',
      component: EventsView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/billing',
      name: 'billing',
      component: BillingView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/plans',
      name: 'plans',
      component: PlansView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/affiliate',
      name: 'affiliate',
      component: AffiliateView,
      meta: { requiresAuth: true, title: 'Affiliate | PayGlue' },
    },
    {
      path: '/t/:tenantSlug/preferences',
      name: 'preferences',
      component: PreferencesView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/thank-you',
      name: 'onboarding-thank-you',
      component: OnboardingThankYouView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    // Catch-all. The private repo renders a 404 page here; OSS has no
    // marketing pages, so an unknown path just goes back to the entry point
    // (which itself redirects to login when unauthenticated). Must stay last.
    {
      path: '/:pathMatch(.*)*',
      redirect: { name: 'dashboard-entry' },
    },
  ],
})

router.beforeEach(async (to) => {
  const session = useSessionStore()
  if (!session.isAuthenticated && !session.isLoading && !to.meta.skipBootstrap) {
    await session.bootstrap()
  }

  // (The private repo carries payglue.io <-> app.payglue.io dual-domain
  // redirect logic here; a self-hosted install has one origin, so it is gone.)

  const requiresAuth = Boolean(to.meta.requiresAuth)
  if (!requiresAuth) {
    return true
  }

  if (!session.idToken || !session.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (to.name !== 'auth-mfa-challenge') {
    const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
    if (aal && aal.nextLevel === 'aal2' && aal.currentLevel !== 'aal2') {
      return { name: 'auth-mfa-challenge' }
    }
  }

  if (
    session.memberships.length === 0 &&
    to.name !== 'tenant-onboarding' &&
    to.name !== 'tenant-select'
  ) {
    return { name: 'tenant-onboarding' }
  }

  if (to.meta.requiresTenantMatch) {
    const routeTenantSlug = String(to.params.tenantSlug ?? '')
    const membership = session.memberships.find((m) => m.tenant_slug === routeTenantSlug)
    if (!membership) {
      return { name: 'tenant-select' }
    }

    // PG-141: a paused tenant stays in the switcher (so it's still visible
    // and reachable for an upgrade), but every other route bounces to the
    // paused-state page instead of the normal dashboard.
    if (membership.status === 'paused' && to.name !== 'tenant-paused') {
      return { name: 'tenant-paused', params: { tenantSlug: routeTenantSlug } }
    }

    if (session.activeTenantSlug !== routeTenantSlug) {
      session.setActiveTenant(routeTenantSlug)
    }
  }

  return true
})

const DEFAULT_TITLE = 'PayGlue | Connect any payment provider to Ghost CMS'

const resolve = (
  value: unknown,
  route: RouteLocationNormalized,
): string | null => {
  if (typeof value === 'function') return (value as (r: RouteLocationNormalized) => string)(route)
  return typeof value === 'string' ? value : null
}

router.afterEach((to) => {
  if (typeof document === 'undefined') return

  document.title = resolve(to.meta.title, to) ?? DEFAULT_TITLE

  const description = resolve(to.meta.description, to)
  let tag = document.querySelector('meta[name="description"]')
  if (description) {
    if (!tag) {
      tag = document.createElement('meta')
      tag.setAttribute('name', 'description')
      document.head.appendChild(tag)
    }
    tag.setAttribute('content', description)
  } else {
    // Dashboard routes have no description of their own; leaving the previous
    // page's text in place would be worse than none at all.
    tag?.remove()
  }

  // Same reasoning as the description: the tag has to be removed again on the
  // way out, or one noindex route would quietly de-list every page visited
  // after it in the same session.
  let robots = document.querySelector('meta[name="robots"]')
  if (to.meta.noindex) {
    if (!robots) {
      robots = document.createElement('meta')
      robots.setAttribute('name', 'robots')
      document.head.appendChild(robots)
    }
    robots.setAttribute('content', 'noindex, nofollow')
  } else {
    robots?.remove()
  }
})

export default router

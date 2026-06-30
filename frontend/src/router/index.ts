// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { createRouter, createWebHistory } from 'vue-router'
import { useSessionStore } from '../stores/session'

const LoginView = () => import('../views/LoginView.vue')
const SignupView = () => import('../views/SignupView.vue')
const DashboardEntryView = () => import('../views/DashboardEntryView.vue')
const DashboardPreviewView = () => import('../views/DashboardPreviewView.vue')
const TennantDevView = () => import('../views/TennantDevView.vue')
const TenantSelectView = () => import('../views/TenantSelectView.vue')
const TenantOnboardingView = () => import('../views/TenantOnboardingView.vue')
const DashboardView = () => import('../views/DashboardView.vue')
const InstallationView = () => import('../views/InstallationView.vue')
const PaywallConfigView = () => import('../views/PaywallConfigView.vue')
const BuyButtonView = () => import('../views/BuyButtonView.vue')
const MappingsView = () => import('../views/MappingsView.vue')
const TeamView = () => import('../views/TeamView.vue')
const PricingTableView = () => import('../views/PricingTableView.vue')
const EventsView = () => import('../views/EventsView.vue')
const BillingView = () => import('../views/BillingView.vue')
const PreferencesView = () => import('../views/PreferencesView.vue')
const OnboardingThankYouView = () => import('../views/OnboardingThankYouView.vue')
const ConnectionGhostView = () => import('../views/ConnectionGhostView.vue')
const ConnectionPolarView = () => import('../views/ConnectionPolarView.vue')
const ConnectionLemonSqueezyView = () => import('../views/ConnectionLemonSqueezyView.vue')
const ConnectionPayPalView = () => import('../views/ConnectionPayPalView.vue')
const ConnectionStripeView = () => import('../views/ConnectionStripeView.vue')
const OrganizationView = () => import('../views/OrganizationView.vue')
const AuthCallbackView = () => import('../views/AuthCallbackView.vue')
const ResetPasswordView = () => import('../views/ResetPasswordView.vue')
const AuthResetView = () => import('../views/AuthResetView.vue')
const WelcomeView = () => import('../views/WelcomeView.vue')

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, behavior: 'smooth' }
    return { top: 0 }
  },
  routes: [
    {
      path: '/',
      redirect: { name: 'login' },
    },
    {
      path: '/auth/callback',
      name: 'auth-callback',
      component: AuthCallbackView,
    },
    {
      path: '/auth/reset',
      name: 'auth-reset',
      component: AuthResetView,
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
      path: '/dashboard-preview',
      name: 'dashboard-preview',
      component: DashboardPreviewView,
    },
    {
      path: '/tennant/dev',
      name: 'tennant-dev',
      component: TennantDevView,
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
      redirect: (to) => `/t/${to.params.tenantSlug}/connection/ghost`,
    },
    {
      path: '/t/:tenantSlug/connection/ghost',
      name: 'connection-ghost',
      component: ConnectionGhostView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/polar',
      name: 'connection-polar',
      component: ConnectionPolarView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/lemonsqueezy',
      name: 'connection-lemonsqueezy',
      component: ConnectionLemonSqueezyView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/paypal',
      name: 'connection-paypal',
      component: ConnectionPayPalView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/connection/stripe',
      name: 'connection-stripe',
      component: ConnectionStripeView,
      meta: { requiresAuth: true, requiresTenantMatch: true },
    },
    {
      path: '/t/:tenantSlug/organization',
      name: 'organization',
      component: OrganizationView,
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
  ],
})

router.beforeEach(async (to) => {
  const session = useSessionStore()
  if (!session.isAuthenticated && !session.isLoading) {
    await session.bootstrap()
  }

  const requiresAuth = Boolean(to.meta.requiresAuth)
  if (!requiresAuth) {
    return true
  }

  if (!session.idToken || !session.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
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
    const hasMembership = session.memberships.some((m) => m.tenant_slug === routeTenantSlug)
    if (!hasMembership) {
      return { name: 'tenant-select' }
    }

    if (session.activeTenantSlug !== routeTenantSlug) {
      session.setActiveTenant(routeTenantSlug)
    }
  }

  return true
})

export default router

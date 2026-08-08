// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// First run of a self-hosted installation (PG-237). What matters here is not
// that the form submits, it is that it cannot promise something the backend
// then refuses, and that the licence is stated where somebody setting this up
// will actually read it.

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/vue'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../lib/authProvider', () => ({
  bootstrapFirstAccount: vi.fn(),
  installationNeedsSetup: vi.fn(() => true),
  capabilities: vi.fn(() => ({
    magicLink: false,
    oauth: false,
    mfa: false,
    emailChange: false,
    passwordSignIn: true,
    profileMetadata: false,
  })),
}))

import { bootstrapFirstAccount, installationNeedsSetup } from '../../lib/authProvider'
import SetupWizardView from '../SetupWizardView.vue'

const buildRouter = () =>
  createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/setup', name: 'setup', component: SetupWizardView },
      { path: '/tenant/create', name: 'tenant-onboarding', component: { template: '<div>Publication</div>' } },
      { path: '/login', name: 'login', component: { template: '<div>Sign in</div>' } },
    ],
  })

const renderWizard = async () => {
  const router = buildRouter()
  router.push('/setup')
  await router.isReady()
  render(SetupWizardView, { global: { plugins: [router] } })
  return router
}

const chooseLocal = async () => {
  await fireEvent.click(screen.getByText(/just trying it out on this device/i))
  await fireEvent.click(screen.getByRole('button', { name: /continue/i }))
}

describe('SetupWizardView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(installationNeedsSetup).mockReturnValue(true)
  })

  it('states the licence boundary where it is read, without asking for consent', async () => {
    await renderWizard()
    // The permitted side and the excluded side both have to be there. Naming
    // only one of them is what turns a note into a misrepresentation.
    expect(screen.getByText(/commercially inside your own business/i)).toBeInTheDocument()
    expect(screen.getByText(/hosted or managed service/i)).toBeInTheDocument()
    // It is a note, not a gate: no checkbox to tick.
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('will not continue until a way to sign in has been picked', async () => {
    await renderWizard()
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()
    await fireEvent.click(screen.getByText(/just trying it out on this device/i))
    expect(screen.getByRole('button', { name: /continue/i })).not.toBeDisabled()
  })

  it('offers instructions rather than fields for a hosted provider', async () => {
    await renderWizard()
    await fireEvent.click(screen.getByText(/running this on a server/i))
    await fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    // Those values are read when the dashboard is built, so a form asking for
    // them would be a form that cannot work.
    expect(screen.getByText(/VITE_SUPABASE_URL/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/project url/i)).not.toBeInTheDocument()
  })

  it('states the password rule the backend actually enforces', async () => {
    await renderWizard()
    await chooseLocal()
    // Django asks for ten, and a screen promising eight would be overruled by
    // the server on submit.
    expect(screen.getByText(/at least 10 characters/i)).toBeInTheDocument()
  })

  it('refuses to submit a password that does not match its confirmation', async () => {
    await renderWizard()
    await chooseLocal()

    await fireEvent.update(screen.getByLabelText(/^email$/i), 'owner@example.com')
    await fireEvent.update(screen.getByLabelText(/^password$/i), 'a-long-enough-one')
    await fireEvent.update(screen.getByLabelText(/confirm password/i), 'something-else')

    expect(screen.getByText(/the two do not match/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create account/i })).toBeDisabled()
    expect(bootstrapFirstAccount).not.toHaveBeenCalled()
  })

  it('creates the account and hands over to the publication step', async () => {
    vi.mocked(bootstrapFirstAccount).mockResolvedValue({
      accessToken: 't',
      userId: 'local:1',
      email: 'owner@example.com',
    })
    const router = await renderWizard()
    await chooseLocal()

    await fireEvent.update(screen.getByLabelText(/^email$/i), 'owner@example.com')
    await fireEvent.update(screen.getByLabelText(/^password$/i), 'a-long-enough-one')
    await fireEvent.update(screen.getByLabelText(/confirm password/i), 'a-long-enough-one')
    await fireEvent.click(screen.getByRole('button', { name: /create account/i }))

    await waitFor(() => {
      expect(bootstrapFirstAccount).toHaveBeenCalledWith('owner@example.com', 'a-long-enough-one')
      expect(router.currentRoute.value.name).toBe('tenant-onboarding')
    })
  })

  it("shows the server's own reason when it rejects the password", async () => {
    // The three rules that cannot be judged in the browser arrive this way, so
    // the message has to survive the trip rather than be replaced by a generic
    // one.
    vi.mocked(bootstrapFirstAccount).mockRejectedValue({
      response: { data: { password: ['This password is too common.'] } },
    })
    await renderWizard()
    await chooseLocal()

    await fireEvent.update(screen.getByLabelText(/^email$/i), 'owner@example.com')
    await fireEvent.update(screen.getByLabelText(/^password$/i), 'password12345')
    await fireEvent.update(screen.getByLabelText(/confirm password/i), 'password12345')
    await fireEvent.click(screen.getByRole('button', { name: /create account/i }))

    await waitFor(() => {
      expect(screen.getByText('This password is too common.')).toBeInTheDocument()
    })
  })

  it('points at the sign-in page once the installation has an account', async () => {
    vi.mocked(installationNeedsSetup).mockReturnValue(false)
    await renderWizard()
    expect(screen.getByText(/already has an account/i)).toBeInTheDocument()
  })
})

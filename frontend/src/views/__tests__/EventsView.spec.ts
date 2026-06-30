// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import EventsView from '../EventsView.vue'
import { useSessionStore } from '../../stores/session'
import { listAuditEvents, listWebhookEvents, replayWebhookEvent } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  return {
    listWebhookEvents: vi.fn(),
    replayWebhookEvent: vi.fn(),
    listAuditEvents: vi.fn(),
  }
})

const setupSession = (role: 'owner' | 'admin' | 'billing_admin' | 'support_readonly') => {
  setActivePinia(createPinia())
  const session = useSessionStore()
  session.$patch({
    user: { id: 'test-uid', email: 'user@example.com' } as any,
    memberships: [{ tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role }],
  })
  session.activeTenantSlug = 'tenant-a'
}

const makeRouter = async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/t/:tenantSlug/events', component: EventsView },
      { path: '/login', component: { template: '<div />' } },
      { path: '/tenant/select', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/mappings', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/team', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/pricing', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/integrations', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/billing', component: { template: '<div />' } },
    ],
  })
  router.push('/t/tenant-a/events')
  await router.isReady()
  return router
}

describe('EventsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listWebhookEvents).mockResolvedValue([
      {
        id: 10,
        tenant_slug: 'tenant-a',
        provider: 'polar',
        status: 'failed',
        attempts: 3,
        next_attempt_at: null,
        last_error: 'upstream timeout',
        endpoint_path: '/t/tenant-a/webhooks/polar/[redacted]/',
        endpoint_metadata: { method: 'POST' },
        payload_snapshot: { event: 'order.paid' },
        headers_snapshot: { 'Content-Type': 'application/json' },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        dead_lettered_at: null,
      },
      {
        id: 11,
        tenant_slug: 'tenant-a',
        provider: 'polar',
        status: 'processed',
        attempts: 1,
        next_attempt_at: null,
        last_error: '',
        endpoint_path: '/t/tenant-a/webhooks/polar/[redacted]/',
        endpoint_metadata: { method: 'POST' },
        payload_snapshot: { event: 'order.paid' },
        headers_snapshot: { 'Content-Type': 'application/json' },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        dead_lettered_at: null,
      },
    ])
    vi.mocked(listAuditEvents).mockResolvedValue([
      {
        id: 101,
        event_type: 'billing_profile_updated',
        target_type: 'billing_profile',
        target_id: 'bp-1',
        actor_membership_id: 1,
        metadata: { updated_fields: ['billing_email'] },
        created_at: '2026-01-01T00:00:00Z',
      },
    ])
    vi.mocked(replayWebhookEvent).mockResolvedValue({
      status: 'accepted',
      tracking_id: 10,
    })
  })

  it('renders webhook events and audit events', async () => {
    setupSession('owner')
    const router = await makeRouter()

    render(EventsView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(screen.getByText(/Webhook events/i)).toBeInTheDocument()
      expect(screen.getByText(/billing_profile_updated/i)).toBeInTheDocument()
    })
  })

  it('replays only failed/dead_letter events for owner/admin', async () => {
    setupSession('admin')
    const router = await makeRouter()

    render(EventsView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /replay event 10/i })).toBeInTheDocument()
    })
    await fireEvent.click(screen.getByRole('button', { name: /replay event 10/i }))

    await waitFor(() => {
      expect(replayWebhookEvent).toHaveBeenCalledWith('tenant-a', 'token', 10)
    })
    expect(screen.getByRole('button', { name: /replay event 11/i })).toBeDisabled()
  })

  it('disables replay for readonly roles and applies audit filters', async () => {
    setupSession('billing_admin')
    const router = await makeRouter()

    render(EventsView, { global: { plugins: [router] } })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /replay event 10/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /replay event 10/i })).toBeDisabled()

    await fireEvent.update(screen.getByLabelText('audit event type'), 'billing_profile_updated')
    await fireEvent.update(screen.getByLabelText('audit target type'), 'billing_profile')
    await fireEvent.update(screen.getByLabelText('audit from date'), '2026-01-01T00:00')
    await fireEvent.update(screen.getByLabelText('audit to date'), '2026-01-02T00:00')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /apply audit filters/i })).not.toBeDisabled()
    })
    await fireEvent.click(screen.getByRole('button', { name: /apply audit filters/i }))

    await waitFor(() => {
      expect(listAuditEvents).toHaveBeenCalled()
    })
    const calls = vi.mocked(listAuditEvents).mock.calls
    const lastArgs = calls[calls.length - 1]
    expect(lastArgs?.[0]).toBe('tenant-a')
    expect(lastArgs?.[1]).toBe('token')
    expect(lastArgs?.[2]?.event_type).toBe('billing_profile_updated')
    expect(lastArgs?.[2]?.target_type).toBe('billing_profile')
    expect(lastArgs?.[2]?.created_at_from).toMatch(/202/)
    expect(lastArgs?.[2]?.created_at_to).toMatch(/202/)
  })
})

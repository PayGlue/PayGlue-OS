// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// The unread dot on the notification bell (PG-228).
//
// It used to be a length check on a hardcoded array, which is a way of saying
// "the list is not empty". That is on permanently, so after the first look it
// told nobody anything. These tests pin what it means now: something is newer than what
// this browser has already seen.
//
// Worth testing rather than clicking: the bell sits behind a login, and a dot
// that is always on looks exactly like a dot that is working.

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import AppShell from '../AppShell.vue'
import { useSessionStore } from '../../stores/session'
import * as api from '../../lib/api'

const SEEN_KEY = 'payglue:changelog-seen'

const ENTRIES = [
  {
    anchor: 'newest-thing',
    title: 'Newest thing',
    body: 'Body one.',
    publishedAt: '2026-08-10T12:00:00+00:00',
  },
  {
    anchor: 'older-thing',
    title: 'Older thing',
    body: 'Body two.',
    publishedAt: '2026-08-01T12:00:00+00:00',
  },
]

const mountShell = async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/login', component: { template: '<div />' } },
      { path: '/tenant/select', component: { template: '<div />' } },
      { path: '/t/:tenantSlug/dashboard', component: { template: '<div />' } },
    ],
  })
  router.push('/t/tenant-a/dashboard')
  await router.isReady()
  render(AppShell, { global: { plugins: [router] } })
}

/** The dot, which carries no text of its own. */
const dot = () => document.querySelector('.bg-indigo-400.rounded-full')

describe('AppShell notification bell', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    setActivePinia(createPinia())
    const session = useSessionStore()
    session.$patch({
      user: { id: 'test-uid', email: 'owner@example.com' } as any,
      accessToken: 'fake-access-token',
      memberships: [
        { tenant_id: 'tid-1', tenant_slug: 'tenant-a', tenant_name: 'Tenant A', role: 'owner' },
      ],
    })
    session.activeTenantSlug = 'tenant-a'
  })

  it('shows what the endpoint returned, not a list written into the file', async () => {
    vi.spyOn(api, 'getChangelogForBell').mockResolvedValue(ENTRIES)

    await mountShell()
    await fireEvent.click(screen.getAllByTitle('Notifications')[0])

    await waitFor(() => expect(screen.getAllByText('Newest thing').length).toBeGreaterThan(0))
  })

  it('points each entry at its own place on the changelog page', async () => {
    // Two or three lines is all the popup has room for, so the entry has to be
    // able to hand somebody the rest. Landing at the top of a page with
    // forty-five entries is not handing them anything.
    vi.spyOn(api, 'getChangelogForBell').mockResolvedValue(ENTRIES)

    await mountShell()
    await fireEvent.click(screen.getAllByTitle('Notifications')[0])

    await waitFor(() => expect(screen.getAllByText('Newest thing').length).toBeGreaterThan(0))
    const targets = Array.from(document.querySelectorAll('a[href^="/changelog/#"]')).map((a) =>
      a.getAttribute('href'),
    )
    expect(targets).toContain('/changelog/#newest-thing')
    expect(targets).toContain('/changelog/#older-thing')
  })

  it('lights the dot when nothing has been seen yet', async () => {
    vi.spyOn(api, 'getChangelogForBell').mockResolvedValue(ENTRIES)

    await mountShell()

    await waitFor(() => expect(dot()).not.toBeNull())
  })

  it('leaves the dot off when the newest entry has already been seen', async () => {
    localStorage.setItem(SEEN_KEY, ENTRIES[0].publishedAt)
    vi.spyOn(api, 'getChangelogForBell').mockResolvedValue(ENTRIES)

    await mountShell()

    await waitFor(() => expect(screen.getAllByTitle('Notifications').length).toBeGreaterThan(0))
    expect(dot()).toBeNull()
  })

  it('lights the dot again when something newer than the stored mark arrives', async () => {
    localStorage.setItem(SEEN_KEY, ENTRIES[1].publishedAt)
    vi.spyOn(api, 'getChangelogForBell').mockResolvedValue(ENTRIES)

    await mountShell()

    await waitFor(() => expect(dot()).not.toBeNull())
  })

  it('clears the dot when the bell is opened, and remembers it', async () => {
    vi.spyOn(api, 'getChangelogForBell').mockResolvedValue(ENTRIES)

    await mountShell()
    await waitFor(() => expect(dot()).not.toBeNull())
    await fireEvent.click(screen.getAllByTitle('Notifications')[0])

    await waitFor(() => expect(dot()).toBeNull())
    expect(localStorage.getItem(SEEN_KEY)).toBe(ENTRIES[0].publishedAt)
  })

  it('stays quiet when the endpoint is unreachable', async () => {
    // A dashboard has no business showing an error because an announcement
    // could not be fetched. Empty and silent is the right failure.
    vi.spyOn(api, 'getChangelogForBell').mockRejectedValue(new Error('offline'))

    await mountShell()
    await fireEvent.click(screen.getAllByTitle('Notifications')[0])

    await waitFor(() => expect(screen.getAllByText("You're all caught up.").length).toBeGreaterThan(0))
    expect(dot()).toBeNull()
  })

  it('says nothing is new on an installation with no entries at all', async () => {
    // What a self-hosted copy sees: the model exists, the table is empty.
    vi.spyOn(api, 'getChangelogForBell').mockResolvedValue([])

    await mountShell()
    await fireEvent.click(screen.getAllByTitle('Notifications')[0])

    await waitFor(() => expect(screen.getAllByText("You're all caught up.").length).toBeGreaterThan(0))
    expect(dot()).toBeNull()
  })
})

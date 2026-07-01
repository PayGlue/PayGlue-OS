// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import TenantSelectView from '../TenantSelectView.vue'
import { useSessionStore } from '../../stores/session'

describe('TenantSelectView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('shows create tenant CTA when memberships are empty', async () => {
    const session = useSessionStore()
    session.$patch({ user: { id: 'test-uid', email: 'owner@example.com' } as any, memberships: [] })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/tenant/select', name: 'tenant-select', component: TenantSelectView },
        { path: '/tenant/create', name: 'tenant-onboarding', component: { template: '<div>Create Tenant</div>' } },
      ],
    })
    router.push('/tenant/select')
    await router.isReady()

    render(TenantSelectView, {
      global: {
        plugins: [router],
      },
    })

    await fireEvent.click(screen.getByRole('link', { name: /create your first organization/i }))
    await waitFor(() => {
      expect(router.currentRoute.value.name).toBe('tenant-onboarding')
    })
  })
})

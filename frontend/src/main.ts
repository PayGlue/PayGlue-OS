// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// HAND-MAINTAINED in the OSS repo (sync script NEVER_SYNC_PATHS): identical
// to the private main.ts minus the cookie-consent/analytics bootstrap, which
// is PayGlue-site infrastructure and would phone home from a self-hosted
// install. Port other changes here by hand as part of each release.

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import router from './router'
import { setAuthErrorHandler } from './lib/api'
import { useSessionStore } from './stores/session'

;(async () => {
  const app = createApp(App)
  const pinia = createPinia()

  app.use(pinia)

  const session = useSessionStore(pinia)
  setAuthErrorHandler(() => {
    session.clearSession()
    router.push({ name: 'login' }).catch(() => undefined)
  })

  // Bootstrap session before installing the router so the initial navigation
  // guard already sees the authenticated state and doesn't redirect to login.
  await session.bootstrap()

  app.use(router)
  app.mount('#app')
})()

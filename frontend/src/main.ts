// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import router from './router'
import { setAuthErrorHandler } from './lib/api'
import { useSessionStore } from './stores/session'
import { initCookieConsent } from './lib/cookieconsent'

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
  initCookieConsent()
})()

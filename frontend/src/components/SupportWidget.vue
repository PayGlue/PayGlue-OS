<script setup lang="ts">
// Support widget in the dashboard: help center, ideas, changelog and the
// support chat from the FeedbackOS instance in VITE_SUPPORT_WIDGET_URL, opened
// from its own launcher bubble in the bottom right corner.
//
// The widget only trusts a verified identity, so the signed-in user is passed
// as a short token the backend signs (/api/v1/support/widget-token). Without
// it every customer would show up as an anonymous visitor. Renders nothing of
// its own; without VITE_SUPPORT_WIDGET_URL it does nothing at all.
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { getSupportWidgetToken } from '../lib/api'
import { useSessionStore } from '../stores/session'

type WidgetFn = ((...args: unknown[]) => void) & { q?: unknown[][] }

declare global {
  interface Window {
    Quackback?: WidgetFn
  }
}

const instanceUrl = ((import.meta.env.VITE_SUPPORT_WIDGET_URL as string | undefined) ?? '').replace(/\/+$/, '')
const session = useSessionStore()

// The SDK and its launcher live on the page, not in this component, so they
// outlive a sign-out and come back on the next sign-in without a second init.
let initialized = false

function installStub() {
  if (window.Quackback) return
  const stub: WidgetFn = (...args: unknown[]) => {
    ;(stub.q = stub.q || []).push(args)
  }
  stub.q = []
  window.Quackback = stub
}

function loadWidget() {
  installStub()
  const src = `${instanceUrl}/api/widget/sdk.js`
  if (!document.querySelector(`script[src="${src}"]`)) {
    const script = document.createElement('script')
    script.async = true
    script.src = src
    document.head.appendChild(script)
  }
  if (!initialized) {
    window.Quackback?.('init', { placement: 'right' })
    initialized = true
  } else {
    window.Quackback?.('showLauncher')
  }
}

async function identify() {
  const idToken = session.idToken
  const user = session.user
  if (!idToken || !user?.id) return
  const meta = (user.user_metadata ?? {}) as Record<string, unknown>
  const name = [meta.first_name, meta.last_name]
    .filter((part): part is string => typeof part === 'string' && part.trim() !== '')
    .join(' ')
  const ssoToken = await getSupportWidgetToken(idToken, name)
  if (ssoToken) window.Quackback?.('identify', { ssoToken })
}

watch(() => session.user?.id, () => {
  if (instanceUrl) void identify()
})

onMounted(() => {
  if (!instanceUrl) return
  loadWidget()
  void identify()
})

onBeforeUnmount(() => {
  if (!instanceUrl) return
  window.Quackback?.('logout')
  window.Quackback?.('hideLauncher')
})
</script>

<template>
  <span hidden />
</template>

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

// Cloudflare Turnstile without the permanent box. The widget is rendered with
// appearance "interaction-only", so in the normal case nobody sees it at all:
// the check runs in the background and a one-line status takes its place.
// Only when Cloudflare asks for a click (before-interactive-callback) does the
// widget get room to show itself.
//
// The token is used exactly as before: the views hand it to Supabase as
// captchaToken. Nothing on the server side changes.
//
// Replaces cfturnstile-vue3, which passed "apperance" (sic), loaded the script
// without render=explicit and emitted event names the views never listened to.

import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export type TurnstileStatus = 'off' | 'running' | 'passed' | 'interactive' | 'failed'

export interface TurnstileRenderOptions {
  sitekey: string
  size?: 'normal' | 'compact' | 'flexible'
  theme?: 'light' | 'dark' | 'auto'
  appearance?: 'always' | 'execute' | 'interaction-only'
  language?: string
  callback?: (token: string) => void
  'expired-callback'?: () => void
  'before-interactive-callback'?: () => void
  'error-callback'?: (code?: string) => boolean | void
}

export interface TurnstileApi {
  render(element: HTMLElement | string, options: TurnstileRenderOptions): string | undefined
  reset(widgetId?: string): void
  remove(widgetId?: string): void
}

declare global {
  interface Window {
    turnstile?: TurnstileApi
    pgTurnstileOnload?: () => void
  }
}

export const TURNSTILE_SCRIPT_URL =
  'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=pgTurnstileOnload'

// How long the background check may take before we stop pretending it will
// finish. Cloudflare normally answers within a second or two.
export const TURNSTILE_FALLBACK_MS = 20_000

let loader: Promise<TurnstileApi> | null = null

/**
 * One script tag for the whole app, however many forms mount a widget. When
 * the API is already on the page (Login to Signup and back) it is used as is.
 */
export function loadTurnstile(): Promise<TurnstileApi> {
  if (window.turnstile) return Promise.resolve(window.turnstile)
  if (loader) return loader
  loader = new Promise<TurnstileApi>((resolve, reject) => {
    window.pgTurnstileOnload = () => {
      if (window.turnstile) resolve(window.turnstile)
      else reject(new Error('Turnstile loaded without an API'))
    }
    const script = document.createElement('script')
    script.src = TURNSTILE_SCRIPT_URL
    script.async = true
    script.defer = true
    script.onerror = () => {
      // Forget the failed attempt so the next mount tries again.
      loader = null
      script.remove()
      reject(new Error('Turnstile script failed to load'))
    }
    document.head.appendChild(script)
  })
  return loader
}

/** Test hook: forget the shared loader between test cases. */
export function resetTurnstileLoader(): void {
  loader = null
}

export interface UseTurnstileOptions {
  sitekey: string
  /** Left unset the widget follows the browser, as it always has here. */
  language?: string
  fallbackMs?: number
}

export function useTurnstile(container: Ref<HTMLElement | null>, options: UseTurnstileOptions) {
  const enabled = Boolean(options.sitekey)
  const token = ref<string | null>(null)
  // No site key (local development): no script, no widget, no status line.
  // The token simply never arrives, which is what happened before as well.
  const status = ref<TurnstileStatus>(enabled ? 'running' : 'off')

  let api: TurnstileApi | null = null
  let widgetId: string | undefined
  let timer: ReturnType<typeof setTimeout> | null = null
  let unmounted = false

  const stopTimer = () => {
    if (timer !== null) clearTimeout(timer)
    timer = null
  }

  const startTimer = () => {
    stopTimer()
    timer = setTimeout(() => {
      timer = null
      // Neither a token nor a request for interaction: give up visibly.
      if (status.value === 'running' && !token.value) status.value = 'failed'
    }, options.fallbackMs ?? TURNSTILE_FALLBACK_MS)
  }

  /** Back to the start: drop the token, show "running", ask for a new one. */
  const reset = () => {
    if (!enabled) return
    token.value = null
    status.value = 'running'
    startTimer()
    if (api && widgetId !== undefined) api.reset(widgetId)
  }

  // Coming back through the back button restores the page from the bfcache
  // with the old token still in memory. Cloudflare already consumed or expired
  // it, so it has to go.
  const onPageShow = (event: PageTransitionEvent) => {
    if (event.persisted) reset()
  }

  onMounted(async () => {
    if (!enabled) return
    window.addEventListener('pageshow', onPageShow)
    startTimer()
    try {
      api = await loadTurnstile()
    } catch {
      stopTimer()
      status.value = 'failed'
      return
    }
    if (unmounted || !container.value) return
    widgetId = api.render(container.value, {
      sitekey: options.sitekey,
      size: 'flexible',
      theme: 'light',
      appearance: 'interaction-only',
      ...(options.language ? { language: options.language } : {}),
      callback: (value: string) => {
        stopTimer()
        token.value = value
        status.value = 'passed'
      },
      'expired-callback': () => {
        token.value = null
        status.value = 'running'
        startTimer()
      },
      'before-interactive-callback': () => {
        stopTimer()
        status.value = 'interactive'
      },
      'error-callback': () => {
        stopTimer()
        token.value = null
        status.value = 'failed'
        // Handled: we show our own message. Turnstile keeps retrying on its
        // own and a later callback turns the line back to "passed".
        return true
      },
    })
  })

  onBeforeUnmount(() => {
    unmounted = true
    stopTimer()
    window.removeEventListener('pageshow', onPageShow)
    if (api && widgetId !== undefined) api.remove(widgetId)
    widgetId = undefined
    token.value = null
  })

  return { token, status, reset }
}

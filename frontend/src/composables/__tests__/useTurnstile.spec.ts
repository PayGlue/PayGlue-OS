// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// A real Turnstile challenge cannot be produced in a test, so the API is a
// stub that records the options it was rendered with. The tests then play
// Cloudflare: they call the callbacks in the order the real widget would and
// check what the person sees in the status line.

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import TurnstileCheck from '../../components/TurnstileCheck.vue'
import {
  TURNSTILE_FALLBACK_MS,
  TURNSTILE_SCRIPT_URL,
  resetTurnstileLoader,
  type TurnstileRenderOptions,
} from '../useTurnstile'

const RUNNING = 'Security check running in the background'
const PASSED = 'Security check passed'
const FAILED = "The security check didn't work. Please reload the page or try again in a moment."

let rendered: TurnstileRenderOptions | null
const api = {
  render: vi.fn((_el: HTMLElement | string, options: TurnstileRenderOptions) => {
    rendered = options
    return 'widget-1'
  }),
  reset: vi.fn(),
  remove: vi.fn(),
}

let mounted: ReturnType<typeof mount>[] = []

const setup = async (sitekey = 'test-sitekey') => {
  const wrapper = mount(TurnstileCheck, { props: { sitekey }, attachTo: document.body })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

const statusLine = (wrapper: ReturnType<typeof mount>) => wrapper.find('[role="status"]')

const persistedPageShow = () => {
  const event = new Event('pageshow') as PageTransitionEvent
  Object.defineProperty(event, 'persisted', { value: true })
  return event
}

describe('TurnstileCheck', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    rendered = null
    api.render.mockClear()
    api.reset.mockClear()
    api.remove.mockClear()
    window.turnstile = api
    resetTurnstileLoader()
  })

  afterEach(() => {
    // Unmount whatever a test left behind, or its pageshow listener would
    // answer the next test's events.
    for (const wrapper of mounted) {
      if (wrapper.vm) wrapper.unmount()
    }
    mounted = []
    vi.useRealTimers()
    delete window.turnstile
    document.body.innerHTML = ''
  })

  it('renders explicitly with the quiet options and shows the running line', async () => {
    const wrapper = await setup()

    expect(api.render).toHaveBeenCalledTimes(1)
    expect(rendered).toMatchObject({
      sitekey: 'test-sitekey',
      size: 'flexible',
      theme: 'light',
      appearance: 'interaction-only',
    })
    expect(rendered).toHaveProperty('language', 'en')
    const line = statusLine(wrapper)
    expect(line.attributes('aria-live')).toBe('polite')
    expect(line.text()).toBe(RUNNING)
    expect(line.isVisible()).toBe(true)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('shows "passed" and hands the token to v-model', async () => {
    const wrapper = await setup()

    rendered!.callback!('tok-1')
    await flushPromises()

    expect(statusLine(wrapper).text()).toBe(PASSED)
    expect(statusLine(wrapper).find('svg').exists()).toBe(true)
    expect(wrapper.emitted('update:modelValue')).toEqual([['tok-1']])
  })

  it('hides the line and opens the widget when Cloudflare asks for interaction', async () => {
    const wrapper = await setup()
    const container = () => wrapper.find('[data-testid="turnstile-check"] > div')
    expect(container().classes()).toContain('h-0')

    rendered!['before-interactive-callback']!()
    await flushPromises()

    expect(statusLine(wrapper).isVisible()).toBe(false)
    expect(container().classes()).not.toContain('h-0')

    // An interaction request cancels the fallback timer.
    vi.advanceTimersByTime(TURNSTILE_FALLBACK_MS + 1)
    await flushPromises()
    expect(statusLine(wrapper).isVisible()).toBe(false)

    // After the click the token arrives and the line comes back.
    rendered!.callback!('tok-2')
    await flushPromises()
    expect(statusLine(wrapper).isVisible()).toBe(true)
    expect(statusLine(wrapper).text()).toBe(PASSED)
    expect(container().classes()).toContain('h-0')
  })

  it('falls back to the failure message after 20 seconds without token or interaction', async () => {
    const wrapper = await setup()

    vi.advanceTimersByTime(TURNSTILE_FALLBACK_MS - 1)
    await flushPromises()
    expect(statusLine(wrapper).text()).toBe(RUNNING)

    vi.advanceTimersByTime(1)
    await flushPromises()
    expect(statusLine(wrapper).text()).toBe(FAILED)
  })

  it('does not fall back once a token arrived', async () => {
    const wrapper = await setup()
    rendered!.callback!('tok-1')
    vi.advanceTimersByTime(TURNSTILE_FALLBACK_MS * 2)
    await flushPromises()
    expect(statusLine(wrapper).text()).toBe(PASSED)
  })

  it('shows the failure message on error and recovers when a retry succeeds', async () => {
    const wrapper = await setup()

    expect(rendered!['error-callback']!('300030')).toBe(true)
    await flushPromises()
    expect(statusLine(wrapper).text()).toBe(FAILED)

    rendered!.callback!('tok-3')
    await flushPromises()
    expect(statusLine(wrapper).text()).toBe(PASSED)
  })

  it('drops the token on expiry and goes back to running, with a fresh timer', async () => {
    const wrapper = await setup()
    rendered!.callback!('tok-1')
    await flushPromises()

    rendered!['expired-callback']!()
    await flushPromises()
    expect(statusLine(wrapper).text()).toBe(RUNNING)
    expect(wrapper.emitted('update:modelValue')!.at(-1)).toEqual([null])

    vi.advanceTimersByTime(TURNSTILE_FALLBACK_MS)
    await flushPromises()
    expect(statusLine(wrapper).text()).toBe(FAILED)
  })

  it('resets token and status when the page comes back from the bfcache', async () => {
    const wrapper = await setup()
    rendered!.callback!('tok-1')
    await flushPromises()

    // A normal pageshow (first load) changes nothing.
    window.dispatchEvent(new Event('pageshow'))
    await flushPromises()
    expect(statusLine(wrapper).text()).toBe(PASSED)

    window.dispatchEvent(persistedPageShow())
    await flushPromises()
    expect(statusLine(wrapper).text()).toBe(RUNNING)
    expect(api.reset).toHaveBeenCalledWith('widget-1')
    expect(wrapper.emitted('update:modelValue')!.at(-1)).toEqual([null])

    vi.advanceTimersByTime(TURNSTILE_FALLBACK_MS)
    await flushPromises()
    expect(statusLine(wrapper).text()).toBe(FAILED)
  })

  it('reset() after a submit asks Cloudflare for a new token', async () => {
    const wrapper = await setup()
    rendered!.callback!('tok-1')
    await flushPromises()

    ;(wrapper.vm as unknown as { reset: () => void }).reset()
    await flushPromises()

    expect(api.reset).toHaveBeenCalledWith('widget-1')
    expect(statusLine(wrapper).text()).toBe(RUNNING)
    expect(wrapper.emitted('update:modelValue')!.at(-1)).toEqual([null])
  })

  it('removes the widget and the pageshow listener on unmount', async () => {
    const wrapper = await setup()
    wrapper.unmount()

    expect(api.remove).toHaveBeenCalledWith('widget-1')
    window.dispatchEvent(persistedPageShow())
    expect(api.reset).not.toHaveBeenCalled()
  })

  it('clears the parent token when the widget unmounts (sign-in sent, password field shown)', async () => {
    const show = ref(true)
    const captchaToken = ref<string | null>(null)
    const Parent = defineComponent({
      setup: () => () =>
        show.value
          ? h(TurnstileCheck, {
              sitekey: 'test-sitekey',
              modelValue: captchaToken.value,
              'onUpdate:modelValue': (value: string | null) => {
                captchaToken.value = value
              },
            })
          : h('p', 'sent'),
    })
    const wrapper = mount(Parent, { attachTo: document.body })
    mounted.push(wrapper)
    await flushPromises()

    rendered!.callback!('tok-1')
    await flushPromises()
    expect(captchaToken.value).toBe('tok-1')

    show.value = false
    await nextTick()
    expect(captchaToken.value).toBeNull()
  })

  it('stays out of the way without a site key (local development)', async () => {
    const wrapper = await setup('')

    expect(api.render).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="turnstile-check"]').exists()).toBe(false)
    vi.advanceTimersByTime(TURNSTILE_FALLBACK_MS * 2)
    await flushPromises()
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })

  it('loads the script once, with render=explicit, when the API is not on the page yet', async () => {
    delete window.turnstile
    const wrapper = await setup()

    const scripts = document.head.querySelectorAll(`script[src="${TURNSTILE_SCRIPT_URL}"]`)
    expect(scripts).toHaveLength(1)
    expect(TURNSTILE_SCRIPT_URL).toContain('render=explicit')
    expect(api.render).not.toHaveBeenCalled()

    window.turnstile = api
    window.pgTurnstileOnload!()
    await flushPromises()
    expect(api.render).toHaveBeenCalledTimes(1)
    expect(statusLine(wrapper).text()).toBe(RUNNING)
    scripts.forEach((s) => s.remove())
  })
})

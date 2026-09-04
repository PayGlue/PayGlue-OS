// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
//
// Third-party embeds that wait for consent.
//
// An iframe from another host loads the moment the page does, and with it go
// the visitor's IP address and whatever cookies that host wants to set. That
// is the kind of thing the cookie banner exists to ask about, so the markup
// ships a placeholder instead of the iframe and this swaps the real thing in
// once the matching consent category is accepted.
//
// Markup contract:
//
//   <div data-consent-embed="media" data-embed-src="https://..." data-embed-title="...">
//     <div style="position:relative;padding-bottom:66.67%;height:0">
//       <button type="button" data-consent-embed-load>...</button>
//     </div>
//   </div>
//
// The button accepts the category on top of whatever the visitor already
// accepted, which then fires the consent hooks that call loadConsentedEmbeds.
//
// data-embed-lazy marks a host that must not load just because consent
// exists, only while it is actually shown: the video overlay on the homepage
// is hidden until somebody opens it, and a player loading behind a closed
// overlay on every visit would defeat the point. Hidden lazy hosts are
// skipped; whoever shows them calls loadConsentedEmbeds again.
//
// Pages without such markup, the dashboard for one, get a no-op.

import * as CookieConsent from 'vanilla-cookieconsent/dist/cookieconsent.esm.js'

const SELECTOR = '[data-consent-embed]'

const hosts = (root: ParentNode): HTMLElement[] => Array.from(root.querySelectorAll<HTMLElement>(SELECTOR))

const isShown = (el: HTMLElement): boolean => el.offsetParent !== null || el.getClientRects().length > 0

export const loadConsentedEmbeds = (acceptedCategories: string[], root: ParentNode = document): void => {
  if (typeof document === 'undefined') return
  hosts(root).forEach((host) => {
    const category = host.dataset.consentEmbed ?? ''
    const src = host.dataset.embedSrc ?? ''
    if (!category || !src || !acceptedCategories.includes(category)) return
    if (host.querySelector('iframe')) return
    if ('embedLazy' in host.dataset && !isShown(host)) return

    const frame = host.querySelector<HTMLElement>('[style*="padding-bottom"]') ?? host
    const button = frame.querySelector<HTMLElement>('[data-consent-embed-load]')
    const iframe = document.createElement('iframe')
    iframe.src = src
    iframe.title = host.dataset.embedTitle ?? ''
    iframe.setAttribute('allow', 'autoplay; fullscreen')
    iframe.setAttribute('allowtransparency', '')
    iframe.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;border:0;'
    // Hidden, not removed: an overlay that closes brings the placeholder back.
    if (button) button.hidden = true
    frame.appendChild(iframe)
  })
}

// For code that shows a lazy host and needs the current consent without
// importing the consent library itself (the marketing site resolves that
// package only through this module's alias).
export const loadEmbedsWithCurrentConsent = (root: ParentNode = document): void => {
  loadConsentedEmbeds(CookieConsent.getUserPreferences().acceptedCategories, root)
}

export const unloadEmbeds = (root: ParentNode = document): void => {
  if (typeof document === 'undefined') return
  hosts(root).forEach((host) => {
    host.querySelectorAll('iframe').forEach((iframe) => iframe.remove())
    const button = host.querySelector<HTMLElement>('[data-consent-embed-load]')
    if (button) button.hidden = false
  })
}

export const wireConsentEmbedButtons = (): void => {
  if (typeof document === 'undefined') return
  hosts(document).forEach((host) => {
    const category = host.dataset.consentEmbed ?? ''
    const button = host.querySelector<HTMLButtonElement>('[data-consent-embed-load]')
    if (!category || !button) return
    button.addEventListener('click', () => {
      // On top of, not instead of: acceptCategory replaces the accepted set,
      // and a visitor who already said yes to analytics must not lose that
      // by pressing play.
      const already = CookieConsent.getUserPreferences().acceptedCategories
      CookieConsent.acceptCategory([...new Set([...already, category])])
    })
  })
}

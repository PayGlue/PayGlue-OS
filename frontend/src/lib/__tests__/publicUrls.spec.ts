// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { describe, expect, it } from 'vitest'
import {
  apiBaseUrl,
  appBaseUrl,
  appDisplayHost,
  embedScript,
  supportEmail,
  webhookUrl,
} from '../publicUrls'

// These assert properties rather than literal addresses on purpose. The whole
// point of the change is that the address depends on where the install runs, so
// a test that pins one would be pinning the bug back in place. Which value the
// helpers resolve to depends on the environment the suite happens to run in.

describe('public URLs', () => {
  it('resolves to something absolute, never a bare path', () => {
    expect(apiBaseUrl()).toMatch(/^https?:\/\/[^/]+$/)
    expect(appBaseUrl()).toMatch(/^https?:\/\/[^/]+$/)
  })

  it('carries no trailing slash, so joins never double up', () => {
    // The trailing slash a copied-in base URL usually has is the classic way to
    // end up with //webhooks and a 404.
    expect(apiBaseUrl().endsWith('/')).toBe(false)
    expect(appBaseUrl().endsWith('/')).toBe(false)
    expect(webhookUrl('polar', 'acme')).not.toContain('//webhooks')
    expect(embedScript('paywall.js', {})).not.toContain('//paywall.js')
  })

  it('builds every public URL from the same resolved base', () => {
    // This is the regression guard. Before, snippets and webhook URLs each
    // carried their own literal, so one could drift from the other and both
    // could point somewhere the operator does not control.
    const base = apiBaseUrl()
    expect(embedScript('button.js', { 'data-id': 'b_42' })).toContain(`src="${base}/button.js"`)
    expect(webhookUrl('polar', 'acme').startsWith(base)).toBe(true)
  })

  it('writes the attributes it is given', () => {
    const snippet = embedScript('button.js', { 'data-id': 'b_42' })
    expect(snippet).toContain('data-id="b_42"')
    expect(snippet).toMatch(/<script src="[^"]+\/button\.js" data-id="b_42"><\/script>/)
  })

  it('renders a valueless attribute as an empty one, which is what defer needs', () => {
    const snippet = embedScript('pricing-table.js', { 'data-table-id': 't1', defer: '' })
    expect(snippet).toContain('data-table-id="t1"')
    expect(snippet).toContain('defer=""')
  })

  it('appends the key to a webhook URL only when there is one', () => {
    expect(webhookUrl('polar', 'acme')).toContain('/webhooks/polar?tenant=acme')
    expect(webhookUrl('polar', 'acme')).not.toContain('key=')
    expect(webhookUrl('polar', 'acme', 'whk_secret')).toContain('&key=whk_secret')
    expect(webhookUrl('polar', 'acme', null)).not.toContain('key=')
    expect(webhookUrl('polar', 'acme', '')).not.toContain('key=')
  })

  it('never invents a support address', () => {
    // Unset means unset. Three places used to name ours, so an unrelated
    // installation pointed its own customers at our inbox (PG-239). Callers
    // hide the contact when this is empty, which only works if it stays empty.
    const contact = supportEmail()
    expect(contact === '' || contact.includes('@')).toBe(true)
    expect(contact).not.toMatch(/payglue\.io|ghostglue\.io/)
  })

  it('strips the scheme for the bare display host', () => {
    expect(appDisplayHost()).not.toContain('://')
    expect(appBaseUrl()).toContain(appDisplayHost())
  })
})

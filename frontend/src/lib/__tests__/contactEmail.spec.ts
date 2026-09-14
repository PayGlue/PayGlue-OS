// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
/**
 * The pattern guarding the support form's contact address.
 *
 * Kept as its own test because the old check was `includes('@')`, which let
 * "someone@example.com," through. That one comma then broke the confirmation
 * email, our internal notification (the address rides along in Reply-To) and
 * the tracker's email link, from a form that had already said "Message sent".
 */
import { describe, it, expect } from 'vitest'

const EMAIL_PATTERN = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]{2,}$/
const ok = (value: string) => EMAIL_PATTERN.test(value.trim())

describe('the contact address pattern', () => {
  it('accepts ordinary addresses', () => {
    for (const value of [
      'someone@example.com',
      'first.last@sub.example.co.uk',
      'a+tag@example.io',
      '  spaced@example.com  ',
    ]) {
      expect(ok(value), value).toBe(true)
    }
  })

  it('rejects the trailing comma that started all this', () => {
    expect(ok('someone@example.com,')).toBe(false)
  })

  it('rejects the other ways a paste goes wrong', () => {
    for (const value of [
      'someone@example.com;',
      'one@example.com, two@example.com',
      'Someone <someone@example.com>',
      'someone@example',
      '@gmail.com',
      'someone@',
      'someone at example.com',
      '',
    ]) {
      expect(ok(value), value).toBe(false)
    }
  })
})

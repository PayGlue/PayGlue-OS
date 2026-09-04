// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md
/**
 * The pattern guarding the support form's contact address.
 *
 * Kept as its own test because the old check was `includes('@')`, which let
 * "nuenni@gmail.com," through. That one comma then broke the confirmation
 * email, our internal notification (the address rides along in Reply-To) and
 * the tracker's email link, from a form that had already said "Message sent".
 */
import { describe, it, expect } from 'vitest'

const EMAIL_PATTERN = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]{2,}$/
const ok = (value: string) => EMAIL_PATTERN.test(value.trim())

describe('the contact address pattern', () => {
  it('accepts ordinary addresses', () => {
    for (const value of [
      'nuenni@gmail.com',
      'first.last@sub.example.co.uk',
      'a+tag@example.io',
      '  spaced@example.com  ',
    ]) {
      expect(ok(value), value).toBe(true)
    }
  })

  it('rejects the trailing comma that started all this', () => {
    expect(ok('nuenni@gmail.com,')).toBe(false)
  })

  it('rejects the other ways a paste goes wrong', () => {
    for (const value of [
      'nuenni@gmail.com;',
      'one@example.com, two@example.com',
      'Nuenni <nuenni@gmail.com>',
      'nuenni@gmail',
      '@gmail.com',
      'nuenni@',
      'nuenni at gmail.com',
      '',
    ]) {
      expect(ok(value), value).toBe(false)
    }
  })
})

// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { describe, expect, it } from 'vitest'
import { buildMatchers, matchesAny, usesPasswordSignIn } from '../passwordSignIn'

const match = (config: string, email: string) => matchesAny(buildMatchers(config), email)

describe('password sign-in list', () => {
  it('is empty unless configured, so nobody gets the password form by default', () => {
    // The important case for the open-source build: an operator who sets
    // nothing must not inherit accounts that skip the magic link.
    expect(usesPasswordSignIn('anyone@example.com')).toBe(false)
    expect(match('', 'anyone@example.com')).toBe(false)
  })

  it('matches one exact address', () => {
    expect(match('me@example.com', 'me@example.com')).toBe(true)
    expect(match('me@example.com', 'someone@example.com')).toBe(false)
  })

  it('matches plus-addressing without matching the bare address', () => {
    expect(match('me+*@example.com', 'me+first@example.com')).toBe(true)
    expect(match('me+*@example.com', 'me+second@example.com')).toBe(true)
    expect(match('me+*@example.com', 'me@example.com')).toBe(false)
  })

  it('matches a whole domain', () => {
    expect(match('*@example.com', 'anyone@example.com')).toBe(true)
    expect(match('*@example.com', 'anyone@other.com')).toBe(false)
  })

  it('does not let a wildcard jump the @ into another domain', () => {
    // Without the [^@] restriction, "*@example.com" would also match
    // "me@evil.com?x=@example.com"-shaped input and hand the password form to
    // an address the operator never listed.
    expect(match('*@example.com', 'me@evil.com')).toBe(false)
    expect(match('me+*@example.com', 'me+x@evil.com')).toBe(false)
  })

  it('treats dots literally rather than as regex wildcards', () => {
    expect(match('me@example.com', 'me@exampleXcom')).toBe(false)
  })

  it('reads several entries and ignores stray whitespace', () => {
    const config = ' me@example.com , *@team.example.com '
    expect(match(config, 'me@example.com')).toBe(true)
    expect(match(config, 'someone@team.example.com')).toBe(true)
    expect(match(config, 'someone@example.com')).toBe(false)
  })

  it('compares case-insensitively', () => {
    expect(match('me@example.com', 'ME@Example.COM')).toBe(true)
  })

  it('never matches an empty address', () => {
    expect(match('*@example.com', '')).toBe(false)
    expect(match('*@example.com', '   ')).toBe(false)
  })
})

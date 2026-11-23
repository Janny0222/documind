import { describe, expect, it } from 'vitest'
import { initials, safeNext } from '@/lib/format'

describe('safeNext (open-redirect guard)', () => {
  it.each([
    ['/w/abc/documents', '/w/abc/documents'],
    ['/invite', '/invite'],
    [null, '/'],
    ['', '/'],
    ['https://evil.example', '/'],
    ['//evil.example', '/'],
    ['/\\evil.example', '/'],
    ['javascript:alert(1)', '/'],
  ])('%s -> %s', (input, expected) => {
    expect(safeNext(input)).toBe(expected)
  })
})

describe('initials', () => {
  it.each([
    ['Jan Michael Reyes', 'JR'],
    ['alice', 'A'],
    ['  ', '?'],
  ])('%s -> %s', (name, expected) => {
    expect(initials(name)).toBe(expected)
  })
})

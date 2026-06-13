import { describe, expect, it } from 'vitest'
import { formatDateTime, formatLocalDate } from '../datetime'

describe('formatDateTime', () => {
  it('treats ISO strings without timezone as Beijing time', () => {
    expect(formatDateTime('2026-05-12T10:58:45')).toBe('2026/05/12 10:58:45')
  })

  it('keeps explicit Beijing timezone timestamps unchanged for display', () => {
    expect(formatDateTime('2026-05-12T18:58:45+08:00')).toBe('2026/05/12 18:58:45')
  })

  it('formats date picker values without UTC day rollback', () => {
    expect(formatLocalDate(new Date(2026, 5, 13, 0, 0, 0))).toBe('2026-06-13')
  })
})

import { describe, expect, it } from 'vitest'
import { targetForInsightShortcut } from '../detailInsightShortcuts'

describe('stock detail insight shortcuts', () => {
  it('maps financial shortcut to financial tab', () => {
    expect(targetForInsightShortcut('financial')).toEqual({ tab: 'financial', anchor: 'stock-detail-insights' })
  })

  it('maps magic-nine shortcut to technical tab and magic-nine anchor', () => {
    expect(targetForInsightShortcut('magic-nine')).toEqual({ tab: 'technical', anchor: 'magic-nine-section' })
  })
})

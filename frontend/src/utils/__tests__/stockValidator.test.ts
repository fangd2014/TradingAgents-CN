import { describe, it, expect } from 'vitest'
import { validateAStock, validateStockCode, getStockCodeFormatHelp, getStockCodeExamples } from '../stockValidator'

describe('stockValidator ETF support', () => {
  it('accepts common A-share ETF codes as A股 instruments', () => {
    for (const code of ['510300', '159915', '588000', '560000']) {
      const result = validateAStock(code)
      expect(result.valid).toBe(true)
      expect(result.market).toBe('A股')
      expect(result.normalizedCode).toBe(code)
    }
  })

  it('auto-detects 6-digit ETF codes as A股', () => {
    expect(validateStockCode('510300').valid).toBe(true)
    expect(validateStockCode('159915').market).toBe('A股')
  })

  it('mentions ETF examples in A-share help text', () => {
    expect(getStockCodeFormatHelp('A股')).toContain('510300')
    expect(getStockCodeExamples('A股')).toContain('510300')
  })
})

import { describe, expect, it, vi } from 'vitest'

vi.mock('@/api/multiMarket', () => ({
  searchStocks: vi.fn(async (_market: string, query: string) => ({
    data: {
      stocks: query === '贵州茅台'
        ? [{ code: '600519', name: '贵州茅台', market: 'CN', source: 'tushare' }]
        : [],
    },
  })),
}))

import { resolveStockInput } from '../stockInputResolver'
import { searchStocks } from '@/api/multiMarket'

describe('resolveStockInput', () => {
  it('keeps valid stock codes without searching', async () => {
    const result = await resolveStockInput('600519', 'A股')

    expect(result.symbol).toBe('600519')
    expect(result.source).toBe('code')
    expect(searchStocks).not.toHaveBeenCalled()
  })

  it('resolves A-share names through stock search', async () => {
    const result = await resolveStockInput('贵州茅台', 'A股')

    expect(result.symbol).toBe('600519')
    expect(result.name).toBe('贵州茅台')
    expect(result.market).toBe('A股')
    expect(result.source).toBe('search')
  })
})

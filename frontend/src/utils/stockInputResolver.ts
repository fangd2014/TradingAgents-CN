import { searchStocks, type StockInfo } from '@/api/multiMarket'
import { validateStockCode } from '@/utils/stockValidator'

export type AnalysisMarket = 'A股' | '美股' | '港股'

export interface StockInputResolution {
  symbol: string
  name?: string
  market: AnalysisMarket
  source: 'code' | 'search'
  stock?: StockInfo
}

const analysisToApiMarket = (market: AnalysisMarket): string => {
  if (market === '港股') return 'HK'
  if (market === '美股') return 'US'
  return 'CN'
}

const apiToAnalysisMarket = (market?: string): AnalysisMarket => {
  if (market === 'HK') return '港股'
  if (market === 'US') return '美股'
  return 'A股'
}

const normalizeCodeForMarket = (stock: StockInfo): string => {
  if (stock.market === 'HK') {
    return String(stock.code || '').padStart(5, '0')
  }
  return String(stock.code || '').toUpperCase()
}

export async function resolveStockInput(
  input: string,
  market: AnalysisMarket,
): Promise<StockInputResolution> {
  const value = String(input || '').trim()
  if (!value) {
    throw new Error('请输入股票代码或名称')
  }

  const validation = validateStockCode(value, market)
  if (validation.valid && validation.normalizedCode) {
    return {
      symbol: validation.normalizedCode,
      market: validation.market || market,
      source: 'code',
    }
  }

  const response = await searchStocks(analysisToApiMarket(market), value, 5)
  const stocks = response.data?.stocks || []
  if (!stocks.length) {
    throw new Error(`未找到与“${value}”匹配的股票，请输入股票代码或更完整的名称`)
  }

  const exact = stocks.find((stock) => stock.name === value || stock.code === value)
  const selected = exact || stocks[0]
  const symbol = normalizeCodeForMarket(selected)
  if (!symbol) {
    throw new Error(`未能解析“${value}”对应的股票代码`)
  }

  return {
    symbol,
    name: selected.name,
    market: apiToAnalysisMarket(selected.market),
    source: 'search',
    stock: selected,
  }
}

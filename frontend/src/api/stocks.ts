import { ApiClient } from './request'

export interface QuoteResponse {
  symbol: string  // 主字段：6位股票代码
  code?: string   // 兼容字段（已废弃）
  full_symbol?: string  // 完整代码（如 000001.SZ）
  name?: string
  market?: string
  price?: number
  change_percent?: number
  amount?: number
  prev_close?: number
  turnover_rate?: number
  amplitude?: number  // 振幅（替代量比）
  trade_date?: string
  updated_at?: string
}

export interface FundamentalsResponse {
  symbol: string  // 主字段：6位股票代码
  code?: string   // 兼容字段（已废弃）
  full_symbol?: string  // 完整代码（如 000001.SZ）
  name?: string
  industry?: string
  market?: string
  sector?: string  // 板块
  pe?: number
  pb?: number
  ps?: number      // 🔥 新增：市销率
  pe_ttm?: number
  pb_mrq?: number
  ps_ttm?: number  // 🔥 新增：市销率（TTM）
  roe?: number
  debt_ratio?: number  // 🔥 新增：负债率
  total_mv?: number
  circ_mv?: number
  turnover_rate?: number
  volume_ratio?: number
  pe_is_realtime?: boolean  // PE是否为实时数据
  pe_source?: string        // PE数据来源
  pe_updated_at?: string    // PE更新时间
  updated_at?: string
}

export interface KlineBar {
  time: string
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number
  amount?: number
}

export interface KlineResponse {
  symbol: string  // 主字段：6位股票代码
  code?: string   // 兼容字段（已废弃）
  period: 'day'|'week'|'month'|'5m'|'15m'|'30m'|'60m'
  limit: number
  adj: 'none'|'qfq'|'hfq'
  source?: string
  items: KlineBar[]
}

export interface NewsItem {
  title: string
  source: string
  time: string
  url: string
  type: 'news' | 'announcement'
}

export interface NewsResponse {
  symbol: string  // 主字段：6位股票代码
  code?: string   // 兼容字段（已废弃）
  days: number
  limit: number
  include_announcements: boolean
  source?: string
  items: NewsItem[]
}

export interface FinancialDetailResponse {
  code: string
  status: string
  income_statement: Record<string, any>[]
  balance_sheet: Record<string, any>[]
  cashflow_statement: Record<string, any>[]
  financial_indicators: Record<string, any>[]
  main_business: Record<string, any>[]
  summary?: Record<string, any>
  source?: string
  last_updated?: string
  is_cached?: boolean
  detail_available?: boolean
  message?: string
  warning?: string
}

export interface IndustryComparisonMetric {
  stock_value: number | null
  industry_median: number | null
  percentile: number | null
  rank: number | null
  sample_count: number
}

export interface IndustryComparisonResponse {
  code: string
  status: string
  industry?: string
  period?: string
  sample_count?: number
  metrics: Record<string, IndustryComparisonMetric>
  source?: string
  last_updated?: string
  is_cached?: boolean
  message?: string
}

export interface TechnicalFactorsResponse {
  code: string
  status: string
  magic_nine: Record<string, any>
  factors: Record<string, any>
  series: Record<string, any>[]
  source?: string
  last_updated?: string
  is_cached?: boolean
  message?: string
}

export type ShareholderScope = 'top10' | 'float_top10'

export interface ShareholderItem {
  code: string
  ts_code?: string
  holder_scope: ShareholderScope
  end_date: string
  ann_date?: string
  rank?: number
  holder_name: string
  holder_name_normalized?: string
  hold_amount?: number | null
  hold_ratio?: number | null
  hold_change?: number | null
  source?: string
  updated_at?: string
  change_type?: string
  amount_delta?: number | null
  ratio_delta?: number | null
  rank_change?: number | null
  previous?: ShareholderItem | null
}

export interface ShareholderChanges {
  new_count: number
  exited_count: number
  increased_count: number
  decreased_count: number
  rank_changed_count: number
  items: ShareholderItem[]
  message?: string
}

export interface ShareholderPeriod {
  period: string
  items: ShareholderItem[]
}

export interface ShareholdersResponse {
  code: string
  scope: ShareholderScope
  status: string
  latest_period?: string | null
  previous_period?: string | null
  source?: string
  last_updated?: string | null
  is_cached?: boolean
  latest: ShareholderItem[]
  changes: ShareholderChanges
  history: ShareholderPeriod[]
  message?: string
  warning?: string
}

export const stocksApi = {
  /**
   * 获取股票行情
   * @param symbol 6位股票代码
   */
  async getQuote(symbol: string) {
    return ApiClient.get<QuoteResponse>(`/api/stocks/${symbol}/quote`)
  },

  /**
   * 获取股票基本面数据
   * @param symbol 6位股票代码
   */
  async getFundamentals(symbol: string) {
    return ApiClient.get<FundamentalsResponse>(`/api/stocks/${symbol}/fundamentals`)
  },

  /**
   * 获取K线数据
   * @param symbol 6位股票代码
   * @param period K线周期
   * @param limit 数据条数
   * @param adj 复权方式
   */
  async getKline(symbol: string, period: KlineResponse['period'] = 'day', limit = 120, adj: KlineResponse['adj'] = 'none') {
    return ApiClient.get<KlineResponse>(`/api/stocks/${symbol}/kline`, { period, limit, adj })
  },

  /**
   * 获取股票新闻
   * @param symbol 6位股票代码
   * @param days 天数
   * @param limit 数量限制
   * @param includeAnnouncements 是否包含公告
   */
  async getNews(symbol: string, days = 30, limit = 50, includeAnnouncements = true) {
    return ApiClient.get<NewsResponse>(`/api/stocks/${symbol}/news`, { days, limit, include_announcements: includeAnnouncements })
  },

  async getFinancialDetail(symbol: string, periods = 8, refresh = false) {
    return ApiClient.get<FinancialDetailResponse>(`/api/stocks/${symbol}/financial-detail`, { periods, refresh })
  },

  async getIndustryComparison(symbol: string, period = 'latest', refresh = false) {
    return ApiClient.get<IndustryComparisonResponse>(`/api/stocks/${symbol}/industry-comparison`, { period, refresh })
  },

  async getTechnicalFactors(symbol: string, limit = 120, refresh = false) {
    return ApiClient.get<TechnicalFactorsResponse>(`/api/stocks/${symbol}/technical-factors`, { limit, refresh })
  },

  async getShareholders(symbol: string, scope: ShareholderScope = 'top10', periods = 4, refresh = false) {
    return ApiClient.get<ShareholdersResponse>(`/api/stocks/${symbol}/shareholders`, { scope, periods, refresh })
  }
}

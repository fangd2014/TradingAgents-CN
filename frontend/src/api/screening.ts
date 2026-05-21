import { ApiClient } from './request'

export interface ScreeningOrderBy { field: string; direction: 'asc' | 'desc' }
export interface ScreeningRunReq {
  market?: 'CN'
  date?: string | null
  adj?: 'qfq' | 'hfq' | 'none'
  conditions: any
  order_by?: ScreeningOrderBy[]
  limit?: number
  offset?: number
}

export interface ScreeningRunItem {
  code: string
  close?: number
  pct_chg?: number
  amount?: number
  ma20?: number
  rsi14?: number
  kdj_k?: number
  kdj_d?: number
  kdj_j?: number
  dif?: number
  dea?: number
  macd_hist?: number
}

export interface ScreeningRunResp { total: number; items: ScreeningRunItem[] }

export interface PresetTrendStartReq {
  limit?: number
  candidate_limit?: number
  industries?: string[]
  float_cap_limit?: number
  min_five_day_turnover?: number
  volume_breakout_multiplier?: number
}

export interface PresetRecentDailyRow {
  trade_date: string
  close?: number | null
  pct_chg?: number | null
  amount?: number | null
  volume?: number | null
}

export interface PresetTrendStartItem extends ScreeningRunItem {
  symbol: string
  name?: string
  market?: string
  industry?: string
  board?: string
  total_mv?: number
  circ_mv?: number
  turnover_rate?: number
  turnover_rate_f?: number
  turnover_rate_date?: string | null
  turnover_rate_source?: string | null
  five_day_change_pct?: number | null
  five_day_total_mv?: number | null
  recent_5d?: PresetRecentDailyRow[]
  matched_conditions?: Record<string, boolean>
  chip_control?: Record<string, any>
}

export interface PresetTraceStep {
  key: string
  label: string
  description?: string
  checked?: number
  pass_count?: number
  fail_count?: number
  remaining_count?: number
  details?: Record<string, any>
}

export interface PresetTraceRejectedSample {
  code?: string
  name?: string
  industry?: string
  failed_stage?: string
  failed_stage_label?: string
  failed_reason?: string
  metrics?: Record<string, any>
}

export interface PresetTrendStartTrace {
  parameters?: Record<string, any>
  steps?: PresetTraceStep[]
  failure_reasons?: Record<string, number>
  sample_rejections?: PresetTraceRejectedSample[]
  matched_count?: number
  returned_count?: number
  took_ms?: number
}

export interface PresetTrendStartResp {
  preset: string
  title: string
  description: string[]
  total: number
  items: PresetTrendStartItem[]
  took_ms?: number
  trace?: PresetTrendStartTrace
}

export interface ScreeningStrategyField {
  key: string
  label: string
  component: 'number' | 'industry-select'
  default?: any
  multiple?: boolean
  min?: number
  max?: number
  step?: number
  precision?: number
  unit?: string
}

export interface ScreeningStrategy {
  id: string
  name: string
  description: string
  tags: string[]
  fields: ScreeningStrategyField[]
}

export interface ScreeningStrategiesResp {
  strategies: ScreeningStrategy[]
  default_strategy_id: string
}

export interface ScreeningTaskResp {
  task_id: string
  status: string
  task_type: 'screening'
  strategy_id: string
  strategy_name: string
}

// 筛选字段配置
export interface FieldInfo {
  name: string
  display_name: string
  field_type: string
  data_type: string
  description: string
  supported_operators: string[]
}

export interface FieldConfigResponse {
  fields: Record<string, FieldInfo>
  categories: Record<string, string[]>
}

// 行业列表响应
export interface IndustryOption {
  value: string
  label: string
  count: number
}

export interface IndustriesResponse {
  industries: IndustryOption[]
  total: number
}

export const screeningApi = {
  run: (payload: ScreeningRunReq, options?: { timeout?: number }) =>
    ApiClient.post<ScreeningRunResp>('/api/screening/run', payload, { timeout: options?.timeout ?? 120000 }),
  runTrendStartPreset: (payload: PresetTrendStartReq, options?: { timeout?: number }) =>
    ApiClient.post<PresetTrendStartResp>('/api/screening/preset/trend-start', payload, { timeout: options?.timeout ?? 180000 }),
  getStrategies: () => ApiClient.get<ScreeningStrategiesResp>('/api/screening/strategies'),
  createIndicatorTask: (payload: ScreeningRunReq, options?: { timeout?: number }) =>
    ApiClient.post<ScreeningTaskResp>('/api/screening/tasks/indicators', payload, { timeout: options?.timeout ?? 120000 }),
  createStrategyTask: (payload: { strategy_id: string; parameters: Record<string, any>; title?: string; strategy_text?: string }, options?: { timeout?: number }) =>
    ApiClient.post<ScreeningTaskResp>('/api/screening/tasks', payload, { timeout: options?.timeout ?? 120000 }),
  getFields: () => ApiClient.get<FieldConfigResponse>('/api/screening/fields'),
  getIndustries: () => ApiClient.get<IndustriesResponse>('/api/screening/industries')
}

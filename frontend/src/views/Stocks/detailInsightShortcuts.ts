export type StockDetailInsightShortcut = 'financial' | 'technical' | 'magic-nine'
export type StockDetailInsightTab = 'financial' | 'industry' | 'technical'

export interface StockDetailInsightTarget {
  tab: StockDetailInsightTab
  anchor: 'stock-detail-insights' | 'magic-nine-section'
}

export function targetForInsightShortcut(action: StockDetailInsightShortcut): StockDetailInsightTarget {
  if (action === 'financial') return { tab: 'financial', anchor: 'stock-detail-insights' }
  if (action === 'technical') return { tab: 'technical', anchor: 'stock-detail-insights' }
  return { tab: 'technical', anchor: 'magic-nine-section' }
}

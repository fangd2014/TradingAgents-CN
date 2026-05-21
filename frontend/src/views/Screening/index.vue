<template>
  <div class="stock-screening">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Search /></el-icon>
        股票筛选
      </h1>
      <p class="page-description">
        通过多维度筛选条件，快速找到符合投资策略的优质股票
      </p>
    </div>

    <!-- 指标选股 -->
    <el-card class="filter-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <div style="display: flex; align-items: center; gap: 12px;">
            <span>指标选股</span>
            <el-tag v-if="currentDataSource" type="info" size="small" effect="plain">
              <el-icon style="vertical-align: middle; margin-right: 4px;"><Connection /></el-icon>
              当前数据源: {{ currentDataSource.name }}
              <span v-if="currentDataSource.token_source_display" style="margin-left: 4px; opacity: 0.8;">
                ({{ currentDataSource.token_source_display }})
              </span>
            </el-tag>
            <el-tag v-else type="warning" size="small">
              <el-icon style="vertical-align: middle; margin-right: 4px;"><Warning /></el-icon>
              无可用数据源
            </el-tag>
          </div>
          <div class="header-actions">
            <el-button type="text" @click="resetFilters">
              <el-icon><Refresh /></el-icon>
              重置
            </el-button>
          </div>
        </div>
      </template>

      <el-form :model="filters" label-width="120px" class="filter-form">
        <el-row :gutter="24">
          <!-- 基础信息 -->
          <el-col :span="8">
            <el-form-item label="市场类型">
              <el-select v-model="filters.market" placeholder="选择市场" disabled>
                <el-option label="A股" value="A股" />
              </el-select>
            </el-form-item>
          </el-col>

          <el-col :span="8">
            <el-form-item label="行业分类">
              <el-select
                v-model="filters.industry"
                placeholder="选择行业"
                multiple
                collapse-tags
                collapse-tags-tooltip
              >
                <el-option
                  v-for="industry in industryOptions"
                  :key="industry.value"
                  :label="industry.label"
                  :value="industry.value"
                />
              </el-select>
            </el-form-item>
          </el-col>

          <el-col :span="8">
            <el-form-item label="市值范围">
              <el-select v-model="filters.marketCapRange" placeholder="选择市值范围">
                <el-option label="小盘股 (< 100亿)" value="small" />
                <el-option label="中盘股 (100-500亿)" value="medium" />
                <el-option label="大盘股 (> 500亿)" value="large" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <!-- 财务指标 -->
          <el-col :span="8">
            <el-form-item label="市盈率 (PE)">
              <el-input-number
                v-model="filters.peRatio.min"
                placeholder="最小值"
                :min="0"
                :precision="2"
                style="width: 45%"
              />
              <span style="margin: 0 8px">-</span>
              <el-input-number
                v-model="filters.peRatio.max"
                placeholder="最大值"
                :min="0"
                :precision="2"
                style="width: 45%"
              />
            </el-form-item>
          </el-col>

          <el-col :span="8">
            <el-form-item label="市净率 (PB)">
              <el-input-number
                v-model="filters.pbRatio.min"
                placeholder="最小值"
                :min="0"
                :precision="2"
                style="width: 45%"
              />
              <span style="margin: 0 8px">-</span>
              <el-input-number
                v-model="filters.pbRatio.max"
                placeholder="最大值"
                :min="0"
                :precision="2"
                style="width: 45%"
              />
            </el-form-item>
          </el-col>

          <el-col :span="8">
            <el-form-item label="ROE (%)">
              <el-input-number
                v-model="filters.roe.min"
                placeholder="最小值"
                :min="0"
                :max="100"
                :precision="2"
                style="width: 45%"
              />
              <span style="margin: 0 8px">-</span>
              <el-input-number
                v-model="filters.roe.max"
                placeholder="最大值"
                :min="0"
                :max="100"
                :precision="2"
                style="width: 45%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <!-- 技术指标 -->
          <el-col :span="8">
            <el-form-item label="涨跌幅 (%)">
              <el-input-number
                v-model="filters.changePercent.min"
                placeholder="最小值"
                :precision="2"
                style="width: 45%"
              />
              <span style="margin: 0 8px">-</span>
              <el-input-number
                v-model="filters.changePercent.max"
                placeholder="最大值"
                :precision="2"
                style="width: 45%"
              />
            </el-form-item>
          </el-col>

          <el-col :span="8">
            <el-form-item label="成交量">
              <el-select v-model="filters.volumeLevel" placeholder="选择成交量水平">
                <el-option label="活跃 (高成交量)" value="high" />
                <el-option label="正常 (中等成交量)" value="medium" />
                <el-option label="清淡 (低成交量)" value="low" />
              </el-select>
            </el-form-item>
          </el-col>

          <!-- 技术形态暂不实现，先隐藏 -->
          <el-col :span="8" v-if="false">
            <el-form-item label="技术形态">
              <el-select
                v-model="filters.technicalPattern"
                placeholder="选择技术形态"
                multiple
                collapse-tags
              >
                <el-option label="突破上升趋势" value="breakout_up" />
                <el-option label="回调买入机会" value="pullback" />
                <el-option label="底部反转" value="bottom_reversal" />
                <el-option label="强势整理" value="consolidation" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 筛选按钮 -->
        <el-row>
          <el-col :span="24">
            <div class="filter-actions">
              <el-button
                type="primary"
                @click="performScreening"
                :loading="screeningLoading"
                size="large"
              >
                <el-icon><Search /></el-icon>
                开始选股
              </el-button>
              <el-button @click="resetFilters" size="large">
                重置条件
              </el-button>
            </div>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <!-- 策略选股 -->
    <el-card class="preset-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <span>策略选股</span>
            <el-tag v-if="selectedStrategy" type="success" size="small" effect="plain" style="margin-left: 8px;">
              {{ selectedStrategy.name }}
            </el-tag>
          </div>
          <el-button
            type="primary"
            @click="performPresetScreening"
            :loading="presetScreeningLoading"
            :disabled="!selectedStrategy"
          >
            <el-icon><Search /></el-icon>
            开始选股
          </el-button>
        </div>
      </template>

      <div class="preset-content">
        <div class="preset-summary">
          <div class="preset-title">策略模板</div>
          <el-select
            v-model="selectedStrategyId"
            placeholder="选择选股策略"
            class="strategy-select"
            @change="resetStrategyParams"
          >
            <el-option
              v-for="strategy in screeningStrategies"
              :key="strategy.id"
              :label="strategy.name"
              :value="strategy.id"
            />
          </el-select>
          <div class="preset-desc">{{ selectedStrategy?.description || '请选择一个策略模板' }}</div>
        </div>
        <div class="preset-rules">
          <el-tag
            v-for="rule in selectedStrategyTags"
            :key="rule"
            type="info"
            effect="plain"
          >
            {{ rule }}
          </el-tag>
        </div>
        <div v-if="selectedStrategyId === 'custom_strategy'" class="custom-strategy-box">
          <div class="custom-strategy-header">
            <span>自定义策略文本</span>
            <el-tag size="small" type="warning" effect="plain">DeepSeek 生成受控 DSL</el-tag>
          </div>
          <el-input
            v-model="customStrategyText"
            type="textarea"
            :rows="12"
            resize="vertical"
            placeholder="输入自然语言、公式或通达信风格策略"
          />
        </div>
        <div class="preset-params">
          <div
            v-for="field in selectedStrategyFields"
            :key="field.key"
            class="param-item"
          >
            <span class="option-label">{{ field.label }}</span>
            <el-select
              v-if="field.component === 'industry-select'"
              v-model="strategyParams[field.key]"
              placeholder="默认不限行业"
              multiple
              collapse-tags
              collapse-tags-tooltip
              clearable
              class="strategy-field"
            >
              <el-option
                v-for="industry in industryOptions"
                :key="industry.value"
                :label="industry.label"
                :value="industry.value"
              />
            </el-select>
            <el-input-number
              v-else
              v-model="strategyParams[field.key]"
              :min="field.min"
              :max="field.max"
              :step="field.step || 1"
              :precision="field.precision"
              controls-position="right"
              class="strategy-field"
            />
            <span v-if="field.unit" class="unit-label">{{ field.unit }}</span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 预设筛选过程 -->
    <el-card
      v-if="resultMode === 'preset' && presetTrace"
      class="preset-trace-panel"
      shadow="never"
    >
      <template #header>
        <div class="card-header">
          <span>预设筛选过程</span>
          <el-tag type="info" effect="plain">
            耗时 {{ presetTrace.took_ms ?? '-' }} ms
          </el-tag>
        </div>
      </template>

      <div class="trace-summary">
        <div class="trace-metric">
          <span class="metric-label">候选上限</span>
          <strong>{{ presetTrace.parameters?.candidate_limit ?? '-' }}</strong>
        </div>
        <div class="trace-metric">
          <span class="metric-label">行业范围</span>
          <strong>{{ presetIndustryMode }}</strong>
        </div>
        <div class="trace-metric">
          <span class="metric-label">最终命中</span>
          <strong>{{ presetTrace.matched_count ?? screeningResults.length }}</strong>
        </div>
        <div class="trace-metric">
          <span class="metric-label">页面返回</span>
          <strong>{{ presetTrace.returned_count ?? screeningResults.length }}</strong>
        </div>
      </div>

      <el-table
        :data="presetTrace.steps || []"
        size="small"
        border
        class="trace-table"
      >
        <el-table-column prop="label" label="步骤" width="150" />
        <el-table-column prop="description" label="判断规则" min-width="260" show-overflow-tooltip />
        <el-table-column prop="checked" label="检查" width="90" align="right" />
        <el-table-column prop="pass_count" label="通过" width="90" align="right" />
        <el-table-column prop="fail_count" label="淘汰" width="90" align="right" />
        <el-table-column prop="remaining_count" label="剩余" width="90" align="right" />
        <el-table-column label="详情" width="90" align="center">
          <template #default="{ row }">
            <el-popover
              v-if="hasTraceDetails(row)"
              placement="left"
              trigger="click"
              width="760"
            >
              <template #reference>
                <el-button type="text" size="small">查看</el-button>
              </template>
              <div class="market-cap-debug">
                <template v-if="row.details?.market_cap_diagnostics">
                  <div class="debug-title">市值字段诊断</div>
                  <div class="debug-grid">
                    <span>阈值：{{ row.details.market_cap_diagnostics.float_cap_limit }} 亿</span>
                    <span>有效股价样本：{{ row.details.market_cap_diagnostics.base_count }}</span>
                    <span>circ_mv存在：{{ row.details.market_cap_diagnostics.circ_exists_count }}</span>
                    <span>circ_mv&gt;0：{{ row.details.market_cap_diagnostics.circ_positive_count }}</span>
                    <span>circ_mv达标：{{ row.details.market_cap_diagnostics.circ_under_limit_count }}</span>
                    <span>total_mv达标：{{ row.details.market_cap_diagnostics.total_under_limit_count }}</span>
                  </div>
                  <div class="debug-subtitle">通过样例</div>
                  <el-table :data="row.details.market_cap_diagnostics.pass_samples || []" size="small" max-height="220">
                    <el-table-column prop="code" label="代码" width="80" />
                    <el-table-column prop="name" label="名称" width="110" />
                    <el-table-column prop="total_mv" label="总市值" width="90" align="right">
                      <template #default="{ row: item }">{{ formatMarketCap(item.total_mv) }}</template>
                    </el-table-column>
                    <el-table-column prop="circ_mv" label="流通市值" width="90" align="right">
                      <template #default="{ row: item }">{{ formatMarketCap(item.circ_mv) }}</template>
                    </el-table-column>
                    <el-table-column prop="effective_mv_source" label="使用字段" width="130" />
                    <el-table-column prop="industry" label="行业" />
                  </el-table>
                  <div class="debug-subtitle">被市值拦截样例</div>
                  <el-table :data="row.details.market_cap_diagnostics.rejected_samples || []" size="small" max-height="220">
                    <el-table-column prop="code" label="代码" width="80" />
                    <el-table-column prop="name" label="名称" width="110" />
                    <el-table-column prop="total_mv" label="总市值" width="90" align="right">
                      <template #default="{ row: item }">{{ formatMarketCap(item.total_mv) }}</template>
                    </el-table-column>
                    <el-table-column prop="circ_mv" label="流通市值" width="90" align="right">
                      <template #default="{ row: item }">{{ formatMarketCap(item.circ_mv) }}</template>
                    </el-table-column>
                    <el-table-column prop="effective_mv_source" label="使用字段" width="130" />
                    <el-table-column prop="industry" label="行业" />
                  </el-table>
                </template>
                <template v-if="row.details?.stage_diagnostics">
                  <div class="debug-title">{{ row.label }}筛选数据</div>
                  <div class="debug-subtitle">通过样例</div>
                  <el-table :data="row.details.stage_diagnostics.pass_samples || []" size="small" max-height="220">
                    <el-table-column prop="code" label="代码" width="80" />
                    <el-table-column prop="name" label="名称" width="110" />
                    <el-table-column prop="industry" label="行业" width="100" />
                    <el-table-column label="关键指标" min-width="320">
                      <template #default="{ row: item }">{{ formatTraceMetrics(item.metrics) }}</template>
                    </el-table-column>
                  </el-table>
                  <div class="debug-subtitle">淘汰样例</div>
                  <el-table :data="row.details.stage_diagnostics.rejected_samples || []" size="small" max-height="220">
                    <el-table-column prop="code" label="代码" width="80" />
                    <el-table-column prop="name" label="名称" width="110" />
                    <el-table-column prop="industry" label="行业" width="100" />
                    <el-table-column prop="failed_reason" label="原因" width="180" show-overflow-tooltip />
                    <el-table-column label="关键指标" min-width="280">
                      <template #default="{ row: item }">{{ formatTraceMetrics(item.metrics) }}</template>
                    </el-table-column>
                  </el-table>
                </template>
              </div>
            </el-popover>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>
      </el-table>

      <div
        v-if="presetFailureReasons.length"
        class="trace-section"
      >
        <div class="trace-section-title">主要淘汰原因</div>
        <div class="failure-tags">
          <el-tag
            v-for="reason in presetFailureReasons"
            :key="reason.label"
            type="warning"
            effect="plain"
          >
            {{ reason.label }}：{{ reason.count }}
          </el-tag>
        </div>
      </div>

      <el-collapse
        v-if="presetTrace.sample_rejections?.length"
        class="trace-section"
      >
        <el-collapse-item title="查看淘汰样例与关键指标" name="samples">
          <el-table
            :data="presetTrace.sample_rejections"
            size="small"
            border
          >
            <el-table-column prop="code" label="代码" width="100" />
            <el-table-column prop="name" label="名称" width="130" />
            <el-table-column prop="industry" label="行业" width="120" />
            <el-table-column prop="failed_stage_label" label="淘汰步骤" width="130" />
            <el-table-column prop="failed_reason" label="原因" min-width="180" show-overflow-tooltip />
            <el-table-column label="关键指标" min-width="260">
              <template #default="{ row }">
                <span class="metric-inline">{{ formatTraceMetrics(row.metrics) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <!-- 筛选结果 -->
    <el-card v-if="screeningResults.length > 0" class="results-panel" shadow="never">
      <template #header>
        <div class="card-header">
          <span>{{ resultTitle }} ({{ screeningResults.length }}只股票)</span>
          <div class="header-actions">
            <el-button
              type="primary"
              @click="batchAnalyze"
              :disabled="selectedStocks.length === 0"
            >
              <el-icon><TrendCharts /></el-icon>
              批量分析 ({{ selectedStocks.length }})
            </el-button>
            <el-button
              v-if="resultMode === 'preset'"
              type="success"
              @click="batchAddFavorites"
              :disabled="selectedStocks.length === 0"
            >
              <el-icon><Star /></el-icon>
              加入自选 ({{ selectedStocks.length }})
            </el-button>
            <el-button type="text" @click="exportResults">
              <el-icon><Download /></el-icon>
              导出结果
            </el-button>
          </div>
        </div>
      </template>

      <!-- 结果表格 -->
      <el-table
        :data="paginatedResults"
        @selection-change="handleSelectionChange"
        stripe
        style="width: 100%"
      >
        <el-table-column type="selection" width="55" />

        <el-table-column prop="code" label="股票代码" width="120">
          <template #default="{ row }">
            <el-link type="primary" @click="viewStockDetail(row)">
              {{ row.code }}
            </el-link>
          </template>
        </el-table-column>

        <el-table-column prop="name" label="股票名称" width="150" />

        <el-table-column prop="industry" label="行业" width="120" />

        <el-table-column prop="board" label="板块" width="100">
          <template #default="{ row }">
            {{ row.board || '-' }}
          </template>
        </el-table-column>

        <el-table-column prop="close" label="当前价格" width="100" align="right">
          <template #default="{ row }">
            <span v-if="row.close">¥{{ row.close?.toFixed(2) }}</span>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>

        <el-table-column prop="pct_chg" label="涨跌幅" width="100" align="right">
          <template #default="{ row }">
            <span v-if="row.pct_chg !== null && row.pct_chg !== undefined" :class="getChangeClass(row.pct_chg)">
              {{ row.pct_chg > 0 ? '+' : '' }}{{ row.pct_chg?.toFixed(2) }}%
            </span>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>

        <el-table-column
          v-if="resultMode === 'preset'"
          prop="five_day_change_pct"
          label="近5日涨幅"
          width="120"
          align="right"
        >
          <template #default="{ row }">
            <span
              v-if="row.five_day_change_pct !== null && row.five_day_change_pct !== undefined"
              :class="getChangeClass(row.five_day_change_pct)"
            >
              {{ row.five_day_change_pct > 0 ? '+' : '' }}{{ row.five_day_change_pct?.toFixed(2) }}%
            </span>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>

        <el-table-column prop="total_mv" label="市值" width="120" align="right">
          <template #default="{ row }">
            {{ formatMarketCap(row.total_mv) }}
          </template>
        </el-table-column>

        <el-table-column
          v-if="resultMode === 'preset'"
          prop="five_day_total_mv"
          label="近5日总市值"
          width="130"
          align="right"
        >
          <template #default="{ row }">
            {{ formatMarketCap(row.five_day_total_mv || row.total_mv) }}
          </template>
        </el-table-column>

        <el-table-column
          v-if="resultMode === 'preset'"
          label="近5日行情"
          width="110"
          align="center"
        >
          <template #default="{ row }">
            <el-popover
              v-if="row.recent_5d && row.recent_5d.length"
              placement="left"
              trigger="click"
              width="360"
            >
              <template #reference>
                <el-button type="text" size="small">查看</el-button>
              </template>
              <el-table :data="row.recent_5d" size="small">
                <el-table-column prop="trade_date" label="日期" width="110" />
                <el-table-column prop="close" label="股价" width="80" align="right">
                  <template #default="{ row: daily }">
                    {{ daily.close !== null && daily.close !== undefined ? `¥${daily.close.toFixed(2)}` : '-' }}
                  </template>
                </el-table-column>
                <el-table-column prop="pct_chg" label="涨幅" width="80" align="right">
                  <template #default="{ row: daily }">
                    <span
                      v-if="daily.pct_chg !== null && daily.pct_chg !== undefined"
                      :class="getChangeClass(daily.pct_chg)"
                    >
                      {{ daily.pct_chg > 0 ? '+' : '' }}{{ daily.pct_chg.toFixed(2) }}%
                    </span>
                    <span v-else>-</span>
                  </template>
                </el-table-column>
                <el-table-column prop="amount" label="成交额" align="right">
                  <template #default="{ row: daily }">
                    {{ formatAmount(daily.amount) }}
                  </template>
                </el-table-column>
              </el-table>
            </el-popover>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>

        <el-table-column
          v-if="resultMode === 'preset'"
          label="筹码判断"
          width="120"
        >
          <template #default="{ row }">
            <el-popover
              v-if="row.chip_control"
              placement="left"
              trigger="click"
              width="360"
            >
              <template #reference>
                <el-button type="text" size="small">
                  {{ row.chip_control.phase || '查看' }}
                </el-button>
              </template>
              <div class="chip-popover">
                <div>阶段：{{ row.chip_control.phase || '-' }}</div>
                <div>评分：{{ row.chip_control.score ?? '-' }}</div>
                <div class="chip-basis">
                  <div
                    v-for="basis in row.chip_control.basis || []"
                    :key="basis"
                  >
                    {{ basis }}
                  </div>
                </div>
              </div>
            </el-popover>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>

        <el-table-column v-if="resultMode !== 'preset'" prop="pe" label="市盈率" width="130" align="right">
          <template #default="{ row }">
            <span v-if="row.pe">
              {{ row.pe?.toFixed(2) }}
              <el-tag v-if="row.pe_is_realtime" type="success" size="small" style="margin-left: 4px">实时</el-tag>
            </span>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>

        <el-table-column v-if="resultMode !== 'preset'" prop="pb" label="市净率" width="130" align="right">
          <template #default="{ row }">
            <span v-if="row.pb">
              {{ row.pb?.toFixed(2) }}
              <el-tag v-if="row.pe_is_realtime" type="success" size="small" style="margin-left: 4px">实时</el-tag>
            </span>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="resultMode !== 'preset'" prop="roe" label="ROE(%)" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.roe !== null && row.roe !== undefined">{{ row.roe?.toFixed(2) }}%</span>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>

        <el-table-column v-if="resultMode !== 'preset'" prop="exchange" label="交易所" width="140">
          <template #default="{ row }">
            {{ row.exchange || '-' }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button type="text" size="small" @click="analyzeSingle(row)">
              分析
            </el-button>
            <el-button type="text" size="small" @click="toggleFavorite(row)">
              <el-icon><Star /></el-icon>
              {{ isFavorited(row.code) ? '取消自选' : '加入自选' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          :total="screeningResults.length"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </el-card>

    <!-- 空状态 -->
    <el-empty
      v-else-if="!screeningLoading && !presetScreeningLoading && hasSearched"
      description="未找到符合条件的股票"
      :image-size="200"
    >
      <el-button type="primary" @click="resetFilters">
        重新筛选
      </el-button>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, TrendCharts, Download, Star, Connection, Warning } from '@element-plus/icons-vue'
import type { StockInfo } from '@/types/analysis'
import type { PresetTrendStartTrace, ScreeningStrategy } from '@/api/screening'
import { screeningApi } from '@/api/screening'
import { favoritesApi } from '@/api/favorites'
import { normalizeMarketForAnalysis, exchangeCodeToMarket, getMarketByStockCode } from '@/utils/market'

// 响应式数据
const screeningLoading = ref(false)
const presetScreeningLoading = ref(false)
const hasSearched = ref(false)
const resultMode = ref<'manual' | 'preset'>('manual')
const presetResultTitle = ref('')
const presetTrace = ref<PresetTrendStartTrace | null>(null)
const screeningResults = ref<Array<StockInfo & Record<string, any>>>([])
const selectedStocks = ref<StockInfo[]>([])
const currentPage = ref(1)
const pageSize = ref(20)

// 路由 & 自选集
const router = useRouter()
const favoriteSet = ref<Set<string>>(new Set())

// 当前数据源仅用于展示。不要在进入筛选页时触发数据源连通性探测，
// 避免外部 Tushare 超时阻塞后端健康检查。
const currentDataSource = ref<{
  name: string
  token_source_display?: string
} | null>({ name: '本地行情数据库' })

// 筛选条件
const filters = reactive({
  market: 'A股',
  industry: [] as string[],
  marketCapRange: '',
  peRatio: { min: null, max: null },
  pbRatio: { min: null, max: null },
  roe: { min: null, max: null },
  changePercent: { min: null, max: null },
  volumeLevel: '',
  technicalPattern: [] as string[]
})

// 行业选项。进入筛选页时不触发后端行业接口，避免外部数据源探测超时拖慢首屏。
const industryOptions = ref<Array<{label: string, value: string, count?: number}>>([
  { label: '半导体', value: '半导体' },
  { label: '电子', value: '电子' },
  { label: '通信', value: '通信' },
  { label: '计算机', value: '计算机' },
  { label: '机器人', value: '机器人' },
  { label: '航天', value: '航天' },
  { label: '军工', value: '军工' },
  { label: '有色金属', value: '有色金属' },
  { label: '化工', value: '化工' },
  { label: '煤炭', value: '煤炭' },
  { label: '电池', value: '电池' },
  { label: '储能', value: '储能' },
  { label: '风电', value: '风电' },
  { label: '银行', value: '银行' },
  { label: '证券', value: '证券' },
  { label: '保险', value: '保险' }
])
const screeningStrategies = ref<ScreeningStrategy[]>([])
const selectedStrategyId = ref('trend_start')
const strategyParams = reactive<Record<string, any>>({})
const defaultCustomStrategyText = `{主力锁仓监控选股}
{底仓锁定识别：在横盘期间下方筹码不松动}
HJ:=5;
横盘天数:=20;
横盘振幅:= (HHV(H,横盘天数)-LLV(L,横盘天数))/LLV(L,横盘天数)<=0.12;
量缩价稳:= MA(VOL,5) < REF(MA(VOL,5),横盘天数)*0.5;
V10:=WINNER(CLOSE*0.85);
V20:=WINNER(CLOSE*0.92);
底部锁仓:= (V20-V10) < 0.1;
选股: 横盘振幅 AND 量缩价稳 AND 底部锁仓;

注意：缩量横盘中若出现连续两个交易日收盘价跌破横盘箱体下沿且成交量放大，应警惕主力换手出货；横盘末期若出现放量阳线突破横盘高点，可视为启动信号。`
const customStrategyText = ref(defaultCustomStrategyText)

// 计算属性
const paginatedResults = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return screeningResults.value.slice(start, end)
})

const resultTitle = computed(() => {
  if (resultMode.value === 'preset') {
    return presetResultTitle.value || '预设选股结果'
  }
  return '筛选结果'
})

const selectedStrategy = computed(() => {
  return screeningStrategies.value.find(strategy => strategy.id === selectedStrategyId.value) || null
})

const selectedStrategyFields = computed(() => selectedStrategy.value?.fields || [])
const selectedStrategyTags = computed(() => selectedStrategy.value?.tags || [])

const presetIndustryMode = computed(() => {
  const selected = presetTrace.value?.parameters?.industries
  if (Array.isArray(selected) && selected.length > 0) {
    return selected.join('、')
  }
  return presetTrace.value?.parameters?.industry_mode || '默认热点行业关键词'
})

const presetFailureReasons = computed(() => {
  const reasons = presetTrace.value?.failure_reasons || {}
  return Object.entries(reasons)
    .map(([label, count]) => ({ label, count: Number(count) || 0 }))
    .sort((a, b) => b.count - a.count)
})

const hasTraceDetails = (row: any) => {
  return Boolean(row?.details?.market_cap_diagnostics || row?.details?.stage_diagnostics)
}

const resetStrategyParams = () => {
  Object.keys(strategyParams).forEach(key => {
    delete strategyParams[key]
  })
  selectedStrategyFields.value.forEach(field => {
    if (field.component === 'industry-select') {
      strategyParams[field.key] = Array.isArray(field.default) ? [...field.default] : []
    } else {
      strategyParams[field.key] = field.default ?? field.min ?? 0
    }
  })
  if (selectedStrategyId.value === 'custom_strategy' && !customStrategyText.value.trim()) {
    customStrategyText.value = defaultCustomStrategyText
  }
}

const loadScreeningStrategies = async () => {
  try {
    const res = await screeningApi.getStrategies()
    const body = (res as any)?.data || res
    screeningStrategies.value = body?.strategies || []
    selectedStrategyId.value = body?.default_strategy_id || screeningStrategies.value[0]?.id || 'trend_start'
    resetStrategyParams()
  } catch {
    screeningStrategies.value = [
      {
        id: 'trend_start',
        name: '中高回落+缩量横盘',
        description: '寻找高位回落后缩量横盘，并在近期开启放量上涨的A股机会。',
        tags: ['冲高回落', '缩量横盘', '放量启动'],
        fields: [
          { key: 'industries', label: '行业范围', component: 'industry-select', multiple: true, default: [] },
          { key: 'limit', label: '结果数量', component: 'number', default: 100, min: 1, max: 200, step: 10, unit: '只' },
          { key: 'candidate_limit', label: '候选扫描', component: 'number', default: 500, min: 20, max: 1000, step: 20, unit: '只' },
          { key: 'float_cap_limit', label: '流通市值上限', component: 'number', default: 500, min: 50, max: 5000, step: 50, unit: '亿元' },
          { key: 'min_five_day_turnover', label: '上一交易日换手', component: 'number', default: 5, min: 0, max: 100, step: 1, unit: '%' },
          { key: 'volume_breakout_multiplier', label: '放量倍数', component: 'number', default: 4, min: 1, max: 20, step: 0.5, precision: 1, unit: '倍' }
        ]
      }
    ]
    selectedStrategyId.value = 'trend_start'
    resetStrategyParams()
  }
}

const openTaskCenter = () => {
  router.push({ name: 'TaskCenterHome', query: { tab: 'running' } })
}

const showTaskSubmitted = async (message: string) => {
  try {
    await ElMessageBox.confirm(message, '选股任务已提交', {
      confirmButtonText: '前往任务中心',
      cancelButtonText: '留在当前页',
      type: 'success'
    })
    openTaskCenter()
  } catch {
    ElMessage.info('选股任务正在后台执行，可随时到任务中心查看')
  }
}

// 方法
const performScreening = async () => {
  screeningLoading.value = true
  hasSearched.value = true
  resultMode.value = 'manual'
  presetResultTitle.value = ''
  presetTrace.value = null

  try {
    // 基于用户真实选择构建 conditions（只拼选中的项，不注入默认技术条件）
    const children: any[] = []

    // 市场类型（仅作为演示，实际后端暂用CN）
    if (filters.market) {
      // 可作为 universe 选择；当未实现时可忽略
    }

    // 行业分类（如果用户选择了行业）
    if (filters.industry && filters.industry.length > 0) {
      // 直接使用数据库中的行业名称，无需映射
      children.push({ field: 'industry', op: 'in', value: filters.industry })
    }

    // 市值范围映射为区间（单位：亿元 → 转换为万元以匹配后端 market_cap 单位）
    const capRangeMap: Record<string, [number, number] | null> = {
      small: [0, 100 * 10000], // <100亿 → < 100*1e4 万元
      medium: [100 * 10000, 500 * 10000],
      large: [500 * 10000, Number.MAX_SAFE_INTEGER],
    }
    const cap = filters.marketCapRange ? capRangeMap[filters.marketCapRange] : null
    if (cap) {
      children.push({ field: 'market_cap', op: 'between', value: cap })
    }
    // 市盈率/市净率/ROE 条件（仅当填写任一端时才拼接）
    if (filters.peRatio.min != null || filters.peRatio.max != null) {
      const lo = filters.peRatio.min ?? 0
      const hi = filters.peRatio.max ?? Number.MAX_SAFE_INTEGER
      children.push({ field: 'pe', op: 'between', value: [lo, hi] })
    }
    if (filters.pbRatio.min != null || filters.pbRatio.max != null) {
      const lo = filters.pbRatio.min ?? 0
      const hi = filters.pbRatio.max ?? Number.MAX_SAFE_INTEGER
      children.push({ field: 'pb', op: 'between', value: [lo, hi] })
    }
    if (filters.roe.min != null || filters.roe.max != null) {
      const lo = filters.roe.min ?? 0
      const hi = filters.roe.max ?? 100
      children.push({ field: 'roe', op: 'between', value: [lo, hi] })
    }

    // 涨跌幅条件
    if (filters.changePercent.min != null || filters.changePercent.max != null) {
      const lo = filters.changePercent.min ?? -100
      const hi = filters.changePercent.max ?? 100
      children.push({ field: 'pct_chg', op: 'between', value: [lo, hi] })
    }

    // 成交量条件（映射为成交额范围，单位：元）
    if (filters.volumeLevel) {
      const volumeRangeMap: Record<string, [number, number]> = {
        high: [1000000000, Number.MAX_SAFE_INTEGER],    // 高成交量：>10亿元
        medium: [300000000, 1000000000],                 // 中等成交量：3亿-10亿元
        low: [0, 300000000]                              // 低成交量：<3亿元
      }
      const volumeRange = volumeRangeMap[filters.volumeLevel]
      if (volumeRange) {
        children.push({ field: 'amount', op: 'between', value: volumeRange })
      }
    }

    // 明确指定：不加任何技术指标相关条件

    const payload = {
      market: 'CN' as const,
      date: undefined,
      adj: 'qfq' as const,
      conditions: { logic: 'AND', children },
      order_by: [{ field: 'market_cap', direction: 'desc' as const }],
      limit: 500,
      offset: 0,
    }

    // 调试日志：打印请求payload
    console.log('🔍 筛选请求 payload:', JSON.stringify(payload, null, 2))
    console.log('🔍 筛选条件 children:', children)

    const res = await screeningApi.createIndicatorTask(payload, { timeout: 120000 })
    const task = (res as any)?.data || res
    screeningResults.value = []
    hasSearched.value = false
    await showTaskSubmitted(`指标选股任务已添加到任务中心。\n任务ID：${task?.task_id || '-'}`)
  } catch (error) {
    ElMessage.error('提交指标选股任务失败，请重试')
  } finally {
    screeningLoading.value = false
  }
}

const performPresetScreening = async () => {
  presetScreeningLoading.value = true
  hasSearched.value = true
  resultMode.value = 'preset'
  currentPage.value = 1

  try {
    const strategy = selectedStrategy.value
    if (!strategy) {
      ElMessage.warning('请先选择选股策略')
      return
    }

    const parameters = JSON.parse(JSON.stringify(strategyParams))
    if (strategy.id === 'custom_strategy' && !customStrategyText.value.trim()) {
      ElMessage.warning('请输入自定义策略文本')
      return
    }
    const response = await screeningApi.createStrategyTask({
      strategy_id: strategy.id,
      title: `策略选股：${strategy.name}`,
      parameters,
      strategy_text: strategy.id === 'custom_strategy' ? customStrategyText.value : undefined
    }, { timeout: 120000 })
    const task = (response as any)?.data || response
    presetResultTitle.value = strategy.name
    presetTrace.value = null
    screeningResults.value = []
    hasSearched.value = false
    await showTaskSubmitted(`策略选股任务已添加到任务中心。\n策略：${strategy.name}\n任务ID：${task?.task_id || '-'}`)
  } catch (error) {
    ElMessage.error('提交策略选股任务失败，请稍后重试')
  } finally {
    presetScreeningLoading.value = false
  }
}

const resetFilters = () => {
  Object.assign(filters, {
    market: 'A股',
    industry: [],
    marketCapRange: '',
    peRatio: { min: null, max: null },
    pbRatio: { min: null, max: null },
    roe: { min: null, max: null },
    changePercent: { min: null, max: null },
    volumeLevel: '',
    technicalPattern: []
  })

  screeningResults.value = []
  selectedStocks.value = []
  hasSearched.value = false
  resultMode.value = 'manual'
  presetResultTitle.value = ''
  presetTrace.value = null
  resetStrategyParams()
  currentPage.value = 1
}

const handleSelectionChange = (selection: StockInfo[]) => {
  selectedStocks.value = selection
}

const batchAnalyze = async () => {
  if (selectedStocks.value.length === 0) {
    ElMessage.warning('请先选择要分析的股票')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定要对选中的 ${selectedStocks.value.length} 只股票进行批量分析吗？`,
      '确认批量分析',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'info'
      }
    )

    // 跳转到批量分析页面（携带统一市场参数）
    router.push({
      name: 'BatchAnalysis',
      query: {
        stocks: selectedStocks.value.map(s => s.code || s.symbol || '').filter(Boolean).join(','),
        market: normalizeMarketForAnalysis(filters.market)
      }
    })
  } catch {
    // 用户取消
  }
}


const analyzeSingle = (stock: StockInfo) => {
  const stockCode = stock.code || stock.symbol || ''
  if (!stockCode) return
  router.push({
    name: 'SingleAnalysis',
    query: {
      stock: stockCode,
      market: normalizeMarketForAnalysis((stock as any).market || filters.market)
    }
  })
}

const viewStockDetail = (stock: StockInfo) => {
  const stockCode = stock.code || stock.symbol || ''
  if (!stockCode) return
  // 跳转到股票详情页面
  router.push({
    name: 'StockDetail',
    params: { code: stockCode }
  })
}

const isFavorited = (code: string) => favoriteSet.value.has(code)

const toggleFavorite = async (stock: StockInfo) => {
  try {
    const code = stock.code || stock.symbol || ''
    if (!code) {
      ElMessage.error('股票代码缺失，无法加入自选')
      return
    }
    if (favoriteSet.value.has(code)) {
      // 取消自选
      const res = await favoritesApi.remove(code)
      if ((res as any)?.success === false) throw new Error((res as any)?.message || '取消失败')
      favoriteSet.value.delete(code)
      ElMessage.success(`已取消自选：${stock.name || code}`)
    } else {
      // 加入自选
      // 根据股票代码判断市场类型
      let marketType = 'A股'
      if ((stock as any).market) {
        // 如果有 market 字段，尝试转换（可能是交易所代码如 "sz", "sh"）
        marketType = exchangeCodeToMarket((stock as any).market)
      } else {
        // 否则根据股票代码判断
        marketType = getMarketByStockCode(code)
      }

      const payload = {
        symbol: code,
        stock_code: code,  // 兼容字段
        stock_name: stock.name || code,
        market: marketType
      }
      const res = await favoritesApi.add(payload)
      if ((res as any)?.success === false) throw new Error((res as any)?.message || '添加失败')
      favoriteSet.value.add(code)
      ElMessage.success(`已加入自选：${stock.name || code}`)
    }
  } catch (error: any) {
    ElMessage.error(error?.message || '自选操作失败')
  }
}

const getTodayFavoriteTag = () => {
  const now = new Date()
  const yyyy = now.getFullYear()
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

const batchAddFavorites = async () => {
  if (selectedStocks.value.length === 0) {
    ElMessage.warning('请先选择要加入自选的股票')
    return
  }

  const tag = getTodayFavoriteTag()
  let successCount = 0
  let skippedCount = 0
  let failedCount = 0

  for (const stock of selectedStocks.value) {
    const code = stock.code || stock.symbol || ''
    if (!code || favoriteSet.value.has(code)) {
      skippedCount += 1
      continue
    }

    try {
      const payload = {
        symbol: code,
        stock_code: code,
        stock_name: stock.name || code,
        market: normalizeMarketForAnalysis((stock as any).market || filters.market),
        tags: [tag]
      }
      const res = await favoritesApi.add(payload)
      if ((res as any)?.success === false) throw new Error((res as any)?.message || '添加失败')
      favoriteSet.value.add(code)
      successCount += 1
    } catch {
      failedCount += 1
    }
  }

  ElMessage.success(`加入自选完成：成功 ${successCount}，跳过 ${skippedCount}，失败 ${failedCount}。标签：${tag}`)
}

const exportResults = () => {
  // 导出筛选结果
  ElMessage.info('导出功能开发中...')
}

const getChangeClass = (changePercent: number) => {
  if (changePercent > 0) return 'text-red'
  if (changePercent < 0) return 'text-green'
  return ''
}

const formatMarketCap = (marketCap: number) => {
  if (marketCap === null || marketCap === undefined || Number.isNaN(Number(marketCap))) {
    return '-'
  }
  if (marketCap >= 10000) {
    return `${(marketCap / 10000).toFixed(2)}万亿`
  } else {
    return `${marketCap.toFixed(2)}亿`
  }
}

const formatAmount = (amount: number | null | undefined) => {
  if (amount === null || amount === undefined || Number.isNaN(Number(amount))) {
    return '-'
  }
  if (amount >= 100000000) {
    return `${(amount / 100000000).toFixed(2)}亿`
  }
  if (amount >= 10000) {
    return `${(amount / 10000).toFixed(2)}万`
  }
  return amount.toFixed(0)
}

const formatTraceNumber = (value: any) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '-'
  }
  const num = Number(value)
  if (Math.abs(num) >= 100000000) {
    return `${(num / 100000000).toFixed(2)}亿`
  }
  if (Math.abs(num) >= 10000) {
    return `${(num / 10000).toFixed(2)}万`
  }
  return Number.isInteger(num) ? String(num) : num.toFixed(2)
}

const formatTraceMetricLabel = (key: string) => {
  const labelMap: Record<string, string> = {
    history_rows: '日线数',
    history_source: '日线来源',
    history_mongo_rows: 'Mongo日线数',
    history_tushare_rows: 'Tushare日线数',
    history_load_error: '日线加载错误',
    total_mv: '总市值',
    sixty_day_high: '60日高点',
    sixty_day_high_date: '高点日期',
    pullback_from_high_pct: '高点回落%',
    sideways_range_pct: '15日振幅%',
    sideways_low: '横盘低点',
    sideways_high: '横盘高点',
    avg_volume_10d: '10日均量',
    avg_volume_20d: '20日均量',
    volume_shrink_ratio: '缩量比例',
    recent_volume_declining: '近量递减',
    abnormal_volume_days: '放量异动天数',
    avg_vol3: '前3日均量',
    latest_volume: '当日成交量',
    volume_ratio_vs_3d: '量比3日',
    day_change_pct: '当日涨幅%',
    latest_open: '开盘',
    latest_close: '收盘',
    ma5: 'MA5',
    ma10: 'MA10',
    ma20: 'MA20',
    ma30: 'MA30',
    ma60: 'MA60',
    up_volume_days_5d: '5日放量上涨天数',
    down_shrink_days_5d: '5日缩量回调天数',
    turnover_rate: '换手率%',
    turnover_rate_f: '自由流通换手率%',
    turnover_rate_trade_date: '换手率日期',
    turnover_rate_source: '换手率来源',
    amount: '成交额'
  }
  return labelMap[key] || key
}

const formatTraceMetrics = (metrics: Record<string, any> | null | undefined) => {
  if (!metrics || Object.keys(metrics).length === 0) {
    return '-'
  }
  return Object.entries(metrics)
    .filter(([, value]) => value !== null && value !== undefined)
    .slice(0, 8)
    .map(([key, value]) => `${formatTraceMetricLabel(key)}=${formatTraceNumber(value)}`)
    .join('，')
}

const handleSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1
}

const handleCurrentChange = (page: number) => {
  currentPage.value = page
}

// 加载自选列表，初始化 favoriteSet
const loadFavorites = async () => {
  try {
    const resp = await favoritesApi.list()
    const list = (resp as any)?.data || resp
    const set = new Set<string>()
    ;(list || []).forEach((item: any) => {
      // 兼容新旧字段
      const code = item.symbol || item.stock_code || item.code
      if (code) set.add(code)
    })
    favoriteSet.value = set
  } catch (e) {
    console.warn('加载自选列表失败，可能未登录或接口不可用。', e)
  }
}

// 生命周期
onMounted(() => {
  // 初始化自选状态
  loadScreeningStrategies()
  loadFavorites()
})
</script>

<style lang="scss" scoped>
.stock-screening {
  .page-header {
    margin-bottom: 24px;

    .page-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 24px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin: 0 0 8px 0;
    }

    .page-description {
      color: var(--el-text-color-regular);
      margin: 0;
    }
  }

  .filter-panel {
    margin-bottom: 24px;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;

      .header-actions {
        display: flex;
        gap: 8px;
      }
    }

    .filter-form {
      .filter-actions {
        display: flex;
        justify-content: center;
        gap: 16px;
        margin-top: 24px;
      }
    }
  }

  .preset-panel {
    margin-bottom: 24px;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .preset-content {
      display: grid;
      gap: 16px;
    }

    .preset-summary {
      display: grid;
      gap: 8px;

      .preset-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }

      .strategy-select {
        max-width: 360px;
        width: 100%;
      }

      .preset-desc {
        color: var(--el-text-color-regular);
        line-height: 1.7;
      }
    }

    .preset-rules {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .preset-params {
      display: flex;
      flex-wrap: wrap;
      gap: 12px 20px;

      .param-item {
        display: flex;
        align-items: center;
        gap: 8px;

        .option-label {
          flex: 0 0 auto;
          min-width: 104px;
          color: var(--el-text-color-regular);
        }

        .strategy-field {
          width: 180px;
        }

        .el-select.strategy-field {
          width: 280px;
        }
      }

      .unit-label {
        color: var(--el-text-color-secondary);
      }
    }

    .custom-strategy-box {
      display: grid;
      gap: 8px;
      margin-bottom: 16px;

      .custom-strategy-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        color: var(--el-text-color-primary);
        font-weight: 600;
      }
    }
  }

  .preset-trace-panel {
    margin-bottom: 24px;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .trace-summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(120px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }

    .trace-metric {
      border: 1px solid var(--el-border-color-lighter);
      border-radius: 6px;
      padding: 10px 12px;
      background: var(--el-fill-color-extra-light);
      display: grid;
      gap: 4px;

      .metric-label {
        font-size: 12px;
        color: var(--el-text-color-secondary);
      }

      strong {
        color: var(--el-text-color-primary);
        font-size: 15px;
      }
    }

    .trace-table {
      width: 100%;
    }

    .trace-section {
      margin-top: 16px;
    }

    .trace-section-title {
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin-bottom: 8px;
    }

    .failure-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .metric-inline {
      color: var(--el-text-color-regular);
      line-height: 1.6;
    }
  }

  .results-panel {
    .pagination-wrapper {
      display: flex;
      justify-content: center;
      margin-top: 24px;
    }
  }

  .text-red {
    color: #f56c6c;
  }

  .text-green {
    color: #67c23a;
  }

  .chip-popover {
    line-height: 1.7;

    .chip-basis {
      margin-top: 8px;
      color: var(--el-text-color-regular);
    }
  }

  .market-cap-debug {
    .debug-title {
      font-weight: 600;
      margin-bottom: 10px;
      color: var(--el-text-color-primary);
    }

    .debug-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px 12px;
      margin-bottom: 12px;
      color: var(--el-text-color-regular);
    }

    .debug-subtitle {
      font-weight: 600;
      margin: 12px 0 8px;
      color: var(--el-text-color-primary);
    }
  }
}
</style>

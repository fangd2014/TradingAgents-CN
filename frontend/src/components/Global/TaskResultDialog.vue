<template>
  <el-dialog v-model="visible" title="任务结果" width="72%">
    <div v-if="result">
      <template v-if="isScreeningResult">
        <div class="screening-summary">
          <div>
            <span class="label">策略</span>
            <strong>{{ screening.strategy_name || '-' }}</strong>
          </div>
          <div>
            <span class="label">命中</span>
            <strong>{{ screening.total ?? screeningItems.length }}</strong>
          </div>
        </div>
        <h4>摘要</h4>
        <div class="markdown-content" v-html="renderMarkdown(result.summary || '无')"></div>
        <el-table :data="screeningItems" stripe max-height="420" style="width: 100%; margin-top: 16px;">
          <el-table-column prop="code" label="代码" width="110">
            <template #default="{ row }">{{ row.code || row.symbol || '-' }}</template>
          </el-table-column>
          <el-table-column prop="name" label="名称" width="140" />
          <el-table-column prop="industry" label="行业" width="120" />
          <el-table-column prop="close" label="价格" width="90" align="right">
            <template #default="{ row }">{{ formatNumber(row.close, 2) }}</template>
          </el-table-column>
          <el-table-column prop="pct_chg" label="涨跌幅" width="100" align="right">
            <template #default="{ row }">{{ formatPercent(row.pct_chg) }}</template>
          </el-table-column>
          <el-table-column prop="total_mv" label="市值" width="110" align="right">
            <template #default="{ row }">{{ formatMarketCap(row.total_mv) }}</template>
          </el-table-column>
          <el-table-column prop="turnover_rate" label="换手率" width="100" align="right">
            <template #default="{ row }">{{ formatPercent(row.turnover_rate ?? row.turnover_rate_f) }}</template>
          </el-table-column>
        </el-table>
      </template>
      <template v-else>
        <h4>建议</h4>
        <div class="markdown-content" v-html="renderMarkdown(result.recommendation || '无')"></div>
        <h4 style="margin-top: 16px;">摘要</h4>
        <div class="markdown-content" v-html="renderMarkdown(result.summary || '无')"></div>
      </template>
    </div>
    <template #footer>
      <el-button @click="emit('close')">关闭</el-button>
      <el-button v-if="!isScreeningResult" type="primary" @click="emit('view-report')">查看报告详情</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps<{ modelValue: boolean; result: any }>()
const emit = defineEmits(['update:modelValue','close','view-report'])

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v)
})

const isScreeningResult = computed(() => props.result?.type === 'screening' || Boolean(props.result?.screening))
const screening = computed(() => props.result?.screening || {})
const screeningItems = computed(() => Array.isArray(screening.value?.items) ? screening.value.items : [])

marked.setOptions({ breaks: true, gfm: true })
const renderMarkdown = (s: string) => { try { return marked.parse(s||'') as string } catch { return s } }

const formatNumber = (value: any, digits = 2) => {
  const num = Number(value)
  return Number.isFinite(num) ? num.toFixed(digits) : '-'
}

const formatPercent = (value: any) => {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return `${num > 0 ? '+' : ''}${num.toFixed(2)}%`
}

const formatMarketCap = (value: any) => {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  if (Math.abs(num) >= 10000) return `${(num / 10000).toFixed(2)}万亿`
  return `${num.toFixed(2)}亿`
}
</script>

<style scoped>
.screening-summary {
  display: flex;
  gap: 24px;
  margin-bottom: 16px;
}

.screening-summary .label {
  color: var(--el-text-color-secondary);
  margin-right: 8px;
}
</style>

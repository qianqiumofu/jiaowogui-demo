<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { api } from '@/shared/api/client'
import { describeError } from '@/shared/stores/session'
import type { StatisticsResult } from '@/shared/api/types'
import StatisticsTrend from './StatisticsTrend.vue'
const props = defineProps<{ parkId: string; parkName: string; query: Record<string, string> }>()
const result = ref<StatisticsResult | null>(null), error = ref(''), loading = ref(false)
let sequence = 0
watch(() => [props.parkId, props.query], async () => {
  const current = ++sequence
  loading.value = true; result.value = null; error.value = ''
  try {
    const response = await api.statistics({ ...props.query, park_org_id: props.parkId, group_by: 'building' })
    if (current === sequence) result.value = response
  } catch (cause) { if (current === sequence) error.value = describeError(cause) }
  finally { if (current === sequence) loading.value = false }
}, { immediate: true, deep: true })
onBeforeUnmount(() => { sequence++ })
</script>
<template><section class="manage-review"><h3>{{ parkName }} · 楼栋明细</h3><p v-if="loading">正在查询楼栋……</p><p v-if="error" role="alert">{{ error }}</p><template v-if="result"><StatisticsTrend :days="result.by_day" :range="result.range" /><div class="manage-table"><table class="stat__table"><thead><tr><th>楼栋</th><th>晚归人数</th><th>晚归夜数</th><th>返宿次数</th><th>在册人数</th></tr></thead><tbody><tr v-for="row in result.rows" :key="String(row.value)"><td>{{ row.label }}</td><td>{{ row.people }}</td><td>{{ row.nights }}</td><td>{{ row.returns }}</td><td>{{ row.enrolled }}</td></tr><tr v-if="!result.rows.length"><td colspan="5">当前条件下没有楼栋数据。</td></tr></tbody></table></div></template></section></template>

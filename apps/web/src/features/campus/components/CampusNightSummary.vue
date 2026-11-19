<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '@/shared/api/client'
import { describeError } from '@/shared/stores/session'
import type { components } from '@/shared/api/schema'
import BusinessDateField from './BusinessDateField.vue'
const night = ref(''), park = ref(''), building = ref(''), message = ref(''), loading = ref(false)
const result = ref<components['schemas']['CampusNightSummary'] | null>(null)
const catalog = ref<components['schemas']['StatisticsOptions'] | null>(null)
let sequence = 0
watch([night, park, building], () => { sequence++; result.value = null; loading.value = false; message.value = '' }, { flush: 'sync' })
watch(park, () => { building.value = '' })
onBeforeUnmount(() => { sequence++ })
onMounted(async () => { try { catalog.value = await api.statisticsFilters() } catch (cause) { message.value = describeError(cause) } })
async function query() {
  const current = ++sequence
  loading.value = true; result.value = null; message.value = ''
  try {
    const response = await api.campusNightSummary({ service_date: night.value, park_org_id: park.value, building_id: building.value })
    if (current === sequence) result.value = response
  } catch (cause) { if (current === sequence) message.value = describeError(cause) }
  finally { if (current === sequence) loading.value = false }
}
</script>
<template><section class="panel"><h2>各楼栋晚归单与当夜负责人</h2><p>按业务夜查看汇总人数、正式返宿人数及当夜负责人。未汇总时人数显示“待汇总”；只读查询，不向园区推送。</p><div class="manage-grid"><BusinessDateField v-model="night" label="查询业务夜" placeholder="默认最近已到汇总时刻的一夜" /><label>宿舍区<select v-model="park"><option value="">全部</option><option v-for="p in catalog?.parks" :key="p.org_id" :value="p.org_id">{{ p.name }}</option></select></label><label>楼栋<select v-model="building"><option value="">全部</option><option v-for="b in catalog?.buildings.filter(b=>!park || b.park_org_id === park)" :key="b.building_id" :value="b.building_id">{{ b.name }}</option></select></label></div><button :disabled="loading" @click="query">查询各楼栋晚归单</button><p v-if="message" role="alert">{{ message }}</p><p v-if="loading">正在查询……</p><p v-else-if="!result">尚未查询。选择条件后点击查询。</p><template v-else><p>{{ result.service_date }} 业务夜 · 汇总时刻 {{ result.summary_due_at.replace('T',' ').slice(0,16) }}</p><div class="manage-table"><table><thead><tr><th>宿舍区 / 楼栋</th><th>汇总情况</th><th>汇总时人数</th><th>正式返宿人数</th><th>当夜负责人</th></tr></thead><tbody><tr v-for="row in result.items" :key="row.building_id"><td>{{ row.park_name }} / {{ row.building_name }}</td><td>{{ row.summary_status === 'SUMMARIZED' ? '已汇总' : '待汇总' }}</td><td>{{ row.headcount ?? '待汇总' }}</td><td>{{ row.returned_count }}</td><td><span v-for="person in row.responsible" :key="person.user_id">{{ person.display_name }}（{{ person.kind === 'FIXED' ? '固定管理' : '当夜代班' }}） </span><span v-if="!row.responsible.length">{{ row.responsible_source === 'UNAVAILABLE' ? '旧汇总未保存负责人' : '暂无负责人' }}</span><br><small>{{ row.responsible_source === 'SNAPSHOT' ? '汇总时保存' : row.responsible_source === 'LIVE' ? '尚未汇总，按现有授权查询' : '历史归属不可追溯' }}</small></td></tr><tr v-if="!result.items.length"><td colspan="5">没有符合条件的楼栋。</td></tr></tbody></table></div></template></section></template>

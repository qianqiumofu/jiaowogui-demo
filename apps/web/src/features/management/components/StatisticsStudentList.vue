<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '@/shared/api/client'
import { describeError } from '@/shared/stores/session'
import type { SchoolStatisticsStudentList, StatisticsFilters } from '@/shared/api/types'

const props = defineProps<{
  title: string
  period: 'DAY' | 'WEEK' | 'MONTH'
  dataset: 'RETURNED' | 'RESERVED' | 'REPEATED'
  options: StatisticsFilters
}>()
const filters = ref({ college_org_id: '', grade: '', park_org_id: '', building_id: '' })
const result = ref<SchoolStatisticsStudentList | null>(null)
const loading = ref(false), error = ref(''), currentPage = ref(1)
const cursors = ref<Array<string | undefined>>([undefined])
let sequence = 0
const buildings = computed(() => props.options.buildings.filter(b => !filters.value.park_org_id || b.park_org_id === filters.value.park_org_id))

function clearResults() {
  sequence++
  result.value = null; error.value = ''; loading.value = false
  currentPage.value = 1; cursors.value = [undefined]
}
watch(() => filters.value.park_org_id, () => {
  if (!buildings.value.some(b => b.building_id === filters.value.building_id)) filters.value.building_id = ''
}, { flush: 'sync' })
watch([filters, () => props.period, () => props.dataset], clearResults, { deep: true, flush: 'sync' })
onBeforeUnmount(() => { sequence++ })

async function query(page = 1, cursor?: string) {
  const requestSequence = ++sequence
  loading.value = true; error.value = ''; result.value = null
  try {
    const response = await api.schoolStatisticsStudents({ ...filters.value, period: props.period, dataset: props.dataset, cursor })
    if (requestSequence !== sequence) return
    result.value = response
    currentPage.value = page
    cursors.value[page - 1] = cursor
  } catch (cause) {
    if (requestSequence === sequence) error.value = describeError(cause)
  } finally {
    if (requestSequence === sequence) loading.value = false
  }
}
function firstQuery() { cursors.value = [undefined]; void query() }
function reset() { filters.value = { college_org_id: '', grade: '', park_org_id: '', building_id: '' }; clearResults() }
</script>

<template>
  <details class="panel statistics-list">
    <summary>{{ title }} · 展开筛选与查询</summary>
    <p>名单默认不加载。选择筛选条件后点击“查询”；全部条件为“全部”时，点击“查询”显示全部范围内的分页结果。</p>
    <form class="manage-grid" @submit.prevent="firstQuery">
      <label>学生学院<select v-model="filters.college_org_id"><option value="">全部</option><option v-for="c in options.colleges" :key="c.org_id" :value="c.org_id">{{ c.name }}</option></select></label>
      <label>年级<select v-model="filters.grade"><option value="">全部</option><option v-for="g in options.grades" :key="g" :value="g">{{ g }} 级</option></select></label>
      <label>宿舍区<select v-model="filters.park_org_id"><option value="">全部</option><option v-for="p in options.parks" :key="p.org_id" :value="p.org_id">{{ p.name }}</option></select></label>
      <label>楼栋<select v-model="filters.building_id"><option value="">全部</option><option v-for="b in buildings" :key="b.building_id" :value="b.building_id">{{ b.name }}</option></select></label>
      <div class="manage-actions"><button type="submit" :disabled="loading">查询</button><button type="button" @click="reset">重置</button></div>
    </form>
    <p v-if="loading" role="status">正在查询……</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <template v-else-if="result">
      <p role="status">符合条件 {{ result.total_matches }} 人 · 第 {{ currentPage }} 页</p>
      <div class="manage-table"><table><thead><tr><th>学号 / 姓名</th><th>学院 / 年级</th><th>宿舍区 / 楼栋</th><th>{{ dataset === 'RESERVED' ? '预约业务夜' : '晚归夜数 / 业务夜' }}</th></tr></thead>
        <tbody><tr v-for="student in result.items" :key="student.student_id">
          <td>{{ student.school_id }}<br>{{ student.display_name }}</td><td>{{ student.college_name }}<br>{{ student.grade }} 级</td>
          <td>{{ student.park_name }} / {{ student.building_name }}</td>
          <td><strong v-if="dataset !== 'RESERVED'">{{ student.return_nights }} 夜</strong><br v-if="dataset !== 'RESERVED'">{{ student.service_dates.join('、') }}</td>
        </tr><tr v-if="!result.items.length"><td colspan="4">当前条件下没有符合的学生。</td></tr></tbody>
      </table></div>
      <div class="manage-actions"><button :disabled="currentPage <= 1 || loading" @click="query(currentPage - 1, cursors[currentPage - 2])">上一页</button><button :disabled="!result.next_cursor || loading" @click="query(currentPage + 1, result.next_cursor ?? undefined)">下一页</button></div>
    </template>
    <p v-else>尚未查询，不展示学生名单。</p>
  </details>
</template>

<style scoped>
summary { cursor: pointer; font-weight: 650; }
button { border: 1px solid var(--line); border-radius: 10px; padding: 9px 16px; background: var(--accent-soft); color: var(--ink); }
button:disabled { opacity: .45; cursor: not-allowed; }
th, td { vertical-align: top; }
</style>

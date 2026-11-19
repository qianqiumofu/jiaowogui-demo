<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import { ApiRequestError, api } from '@/shared/api/client'
import type { ExportJob, SchoolOverview, StatisticsFilters, StatisticsResult } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'
import BusinessDateField from '../components/BusinessDateField.vue'
import StatisticsTrend from '../components/StatisticsTrend.vue'
import StatisticsBreakdown from '../components/StatisticsBreakdown.vue'

const session = useSessionStore()

// 园区看全校，辅导员/思政/学院负责人复用同一表单，但文案与筛选口径限定在本人负责范围。
const isCampus = computed(() => session.context?.active_role === 'CAMPUS')
const scopeText = computed(() => (isCampus.value ? '全校' : '本人负责范围'))

// 发生时住宿归属可解释历史统计，查询与导出固定使用同一口径。
const ATTRIBUTION = 'snapshot'
const formatDate = (value: string) => value.replace(/^(\d{4})-(\d{2})-(\d{2})$/, '$1年$2月$3日')
const GAP_TEXT: Record<string, string> = {
  RESERVATION_SOURCE_UNAVAILABLE:
    '「预约」与「未确认」两列的数据来源尚未落地，本页面按空值显示，不计入晚归判定。',
}

// 与后端 `app/modules/statistics/router.py::DEFAULT_RANGE_NIGHTS` 同一个取值，改那边要改这里。
const DEFAULT_RANGE_NIGHTS = 14

// 分组固定按片区：学院、年级已经能做筛选，全校合计在上方三张卡片里，
// 逐夜明细在下面单独一张表，都不需要再靠一个下拉切换。
const GROUP_BY = 'park'

const EMPTY_PICKS = {
  college_org_id: '',
  park_org_id: '',
  building_id: '',
  grade: '',
  education_level: '',
  date_from: '',
  date_to: '',
}

type PickKey = keyof typeof EMPTY_PICKS

const catalog = ref<StatisticsFilters | null>(null)
const catalogState = ref<'loading' | 'ready' | 'error'>('loading')
const catalogError = ref('')
const picks = ref({ ...EMPTY_PICKS })
type QuickPeriod = 'DAY' | 'WEEK' | 'MONTH' | 'CUSTOM'
const quickPeriod = ref<QuickPeriod>('CUSTOM')
const quickSummary = ref<SchoolOverview | null>(null)
const selectedPark = ref('')
const result = ref<StatisticsResult | null>(null)
const detailQuery = computed(() => ({ ...params.value, date_from: result.value?.range.date_from ?? '', date_to: result.value?.range.date_to ?? '' }))
const queryState = ref<'idle' | 'loading' | 'ready' | 'denied' | 'error'>('idle')
const queryNotice = ref('')

const params = computed(() => {
  const query: Record<string, string> = { group_by: GROUP_BY, attribution: ATTRIBUTION }
  for (const [key, value] of Object.entries(picks.value)) if (value) query[key] = value
  return query
})

// 导出契约要求显式区间，统计则允许留空取默认；补成屏幕上这份区间，两边才不会各算一段。
const exportParams = computed(() => {
  const applied = result.value
  if (!applied) return {}
  return { ...applied.filters, group_by: applied.group_by, attribution: applied.attribution,
    date_from: applied.range.date_from, date_to: applied.range.date_to }
})

const buildingOptions = computed(() => {
  const list = catalog.value?.buildings ?? []
  const park = picks.value.park_org_id
  return park ? list.filter((item) => item.park_org_id === park) : list
})

const FILTER_ORDER: Array<[PickKey, string]> = [
  ['college_org_id', '学院'],
  ['park_org_id', '片区'],
  ['building_id', '楼栋'],
  ['grade', '年级'],
  ['education_level', '培养层次'],
]

// 用后端回传的 filters，说明的就是表格里这份结果，改了下拉还没重算时不会先变。
const activeFilterText = computed(() => {
  const applied = result.value?.filters ?? {}
  const names = FILTER_ORDER.filter(([key]) => applied[key]).map(
    ([key, label]) => `${label}=${labelOf(key, applied[key])}`,
  )
  return names.length ? names.join(' · ') : `无筛选（${scopeText.value}）`
})

function labelOf(key: PickKey, value: string): string {
  if (key === 'education_level') return ({ BACHELOR: '本科', MASTER: '硕士', DOCTORAL: '博士' } as Record<string, string>)[value] ?? value
  if (key === 'grade') return value
  if (key === 'building_id') {
    return catalog.value?.buildings.find((b) => b.building_id === value)?.name ?? value
  }
  if (key === 'college_org_id') {
    return catalog.value?.colleges.find((c) => c.org_id === value)?.name ?? value
  }
  return catalog.value?.parks.find((p) => p.org_id === value)?.name ?? value
}

watch(() => picks.value.park_org_id, (park) => {
  const building = picks.value.building_id
  if (building && park && !buildingOptions.value.some((b) => b.building_id === building))
    picks.value.building_id = ''
})

async function loadCatalog() {
  catalogState.value = 'loading'
  catalogError.value = ''
  try {
    catalog.value = await api.statisticsFilters()
    catalogState.value = 'ready'
  } catch (cause) {
    catalog.value = null
    catalogState.value = 'error'
    catalogError.value = describeError(cause)
  }
}

let sequence = 0
function invalidate() { selectedPark.value = ''; sequence++; quickSummary.value = null; result.value = null; queryState.value = 'idle'; queryNotice.value = '' }
watch([params, quickPeriod], invalidate, { deep: true, flush: 'sync' })
function selectPeriod(period: QuickPeriod) {
  quickPeriod.value = period
  picks.value.date_from = ''; picks.value.date_to = ''
  invalidate()
}

async function query() {
  selectedPark.value = ''
  const requestSequence = ++sequence
  result.value = null
  queryState.value = 'loading'
  queryNotice.value = ''
  try {
    const requestParams = { ...params.value }
    let summary: SchoolOverview | null = null
    if (quickPeriod.value !== 'CUSTOM') {
      summary = await api.campusQuickStatistics({ period: quickPeriod.value,
        college_org_id: picks.value.college_org_id, grade: picks.value.grade, education_level: picks.value.education_level,
        park_org_id: picks.value.park_org_id, building_id: picks.value.building_id })
      if (requestSequence !== sequence) return
      requestParams.date_from = summary.date_from; requestParams.date_to = summary.date_to
    }
    const response = await api.statistics(requestParams)
    if (requestSequence !== sequence) return
    quickSummary.value = summary
    if (requestSequence !== sequence) return
    result.value = response
    queryState.value = 'ready'
  } catch (cause) {
    if (requestSequence !== sequence) return
    result.value = null
    if (cause instanceof ApiRequestError) {
      queryState.value =
        cause.code.startsWith('FORBIDDEN') || cause.code === 'SCOPE_UNRESOLVED' || cause.code === 'OUT_OF_SCOPE'
          ? 'denied'
          : 'error'
    } else {
      queryState.value = 'error'
    }
    queryNotice.value = describeError(cause)
  }
}

function reset() {
  picks.value = { ...EMPTY_PICKS }
  quickPeriod.value = 'CUSTOM'
  invalidate()
}

const jobs = ref<ExportJob[]>([])
const showExports = ref(false)
const deletingExport = ref('')
let jobsSequence = 0
const submitting = ref(false)
const exportNotice = ref('')
const exportError = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let pollsLeft = 0

const STATUS_LABEL: Record<string, string> = {
  PENDING: '排队中',
  RUNNING: '生成中',
  DONE: '可下载',
  FAILED: '生成失败',
}

async function requestExport() {
  if (submitting.value || !result.value) return
  submitting.value = true
  exportNotice.value = ''
  exportError.value = ''
  try {
    await api.createExport(exportParams.value, `web:${crypto.randomUUID()}`)
    showExports.value = true
    await restartPolling()
  } catch (cause) {
    exportError.value = describeError(cause)
  } finally {
    submitting.value = false
  }
}

async function restartPolling() {
  if (timer) clearTimeout(timer)
  pollsLeft = 10
  exportNotice.value = ''
  exportError.value = ''
  await refreshJobs()
}

async function toggleExports() {
  showExports.value = !showExports.value
  jobsSequence++
  if (timer) clearTimeout(timer)
  if (showExports.value) await restartPolling()
}

async function removeExport(job: ExportJob) {
  if (deletingExport.value) return
  deletingExport.value = job.export_id
  exportError.value = ''
  jobsSequence++
  if (timer) clearTimeout(timer)
  try {
    await api.deleteExport(job.export_id)
    jobs.value = jobs.value.filter(item => item.export_id !== job.export_id)
    exportNotice.value = '导出记录已删除。'
    if (showExports.value) await refreshJobs()
  } catch (cause) {
    exportError.value = describeError(cause)
  } finally {
    deletingExport.value = ''
  }
}

async function refreshJobs() {
  if (!showExports.value) return
  const requestSequence = ++jobsSequence
  try {
    const response = await api.myExports()
    if (requestSequence !== jobsSequence || !showExports.value) return
    jobs.value = response.items
    if (jobs.value.some((job) => job.status === 'PENDING' || job.status === 'RUNNING')) schedulePoll()
    else {
      if (timer) clearTimeout(timer)
      exportNotice.value = ''
    }
  } catch (cause) {
    if (requestSequence !== jobsSequence || !showExports.value) return
    exportError.value = describeError(cause)
  }
}

// worker 未启动时任务停在排队：轮询有上限，超时后给出提示而不是无限转圈。
function schedulePoll() {
  if (timer) clearTimeout(timer)
  if (pollsLeft <= 0) {
    exportNotice.value = '文件仍在生成，请稍后点击「刷新任务」查看进度。'
    return
  }
  pollsLeft -= 1
  timer = setTimeout(refreshJobs, 2000)
}

function shownAt(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

async function download(job: ExportJob) {
  exportError.value = ''
  try {
    const file = await api.downloadExport(job.export_id)
    const url = URL.createObjectURL(file.blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.fileName
    link.click()
    URL.revokeObjectURL(url)
  } catch (cause) {
    exportError.value = describeError(cause)
    await refreshJobs()
  }
}

const canExport = computed(() => session.can('export:create'))

onMounted(async () => {
  await loadCatalog()
})

onUnmounted(() => {
  sequence++
  jobsSequence++
  showExports.value = false
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>{{ isCampus ? '全校晚归统计' : '晚归情况查询' }}</h2>
        <button class="panel__reload" type="button" :disabled="queryState === 'loading'" @click="query">
          查询
        </button>
      </header>
      <p class="panel__line">
        按学院、宿舍区、楼栋、年级、培养层次筛选{{ scopeText }}晚归；人数、晚归夜数与返宿次数分开计算，互不相加。{{ isCampus ? '' : '只统计你权限内的学生。' }}
      </p>

      <p v-if="catalogState === 'error'" class="stat__gap">
        筛选选项读不到（{{ catalogError }}），筛选下拉此刻只剩「全部」，不是校区里真的只有一个学院或一个片区。
        后端未启动、或进程版本过旧没有 <code>GET /statistics/filters</code> 时就是这个样子。
        <button class="panel__reload" type="button" @click="loadCatalog">重试读取</button>
      </p>
      <p v-else-if="catalogState === 'loading'" class="panel__line">筛选选项读取中……</p>

      <div class="stat__periods" aria-label="快捷统计周期">
        <button v-for="item in ([['DAY','今日'],['WEEK','本周'],['MONTH','本月'],['CUSTOM','自选日期']] as const)" :key="item[0]" type="button" :aria-pressed="quickPeriod === item[0]" @click="selectPeriod(item[0])">{{ item[1] }}</button>
      </div>
      <p v-if="quickPeriod !== 'CUSTOM'" class="panel__line">{{ quickPeriod === 'DAY' ? '今日分别查看昨夜正式晚归与今夜预约人数。' : quickPeriod === 'WEEK' ? '本周统计最近已结束业务夜所在自然周，周一起至该夜。' : '本月统计最近已结束业务夜所在自然月，月初起至该夜。' }} 点击“查询”后显示结果，日期由服务端确定。</p>
      <div class="stat__filters">
        <label class="stat__field">
          <span>学院</span>
          <select v-model="picks.college_org_id">
            <option value="">全部</option>
            <option v-for="item in catalog?.colleges ?? []" :key="item.org_id" :value="item.org_id">
              {{ item.name }}
            </option>
          </select>
        </label>
        <label class="stat__field">
          <span>宿舍区</span>
          <select v-model="picks.park_org_id">
            <option value="">全部</option>
            <option v-for="item in catalog?.parks ?? []" :key="item.org_id" :value="item.org_id">
              {{ item.name }}（{{ item.building_count }} 栋）
            </option>
          </select>
        </label>
        <label class="stat__field">
          <span>楼栋</span>
          <select v-model="picks.building_id">
            <option value="">全部</option>
            <option v-for="item in buildingOptions" :key="item.building_id" :value="item.building_id">
              {{ item.name }}
            </option>
          </select>
        </label>
        <label class="stat__field">
          <span>培养层次</span>
          <select v-model="picks.education_level">
            <option value="">全部（含层次未同步）</option>
            <option v-for="item in catalog?.education_levels ?? []" :key="item" :value="item">{{ labelOf('education_level', item) }}</option>
          </select>
        </label>
        <label class="stat__field">
          <span>年级</span>
          <select v-model="picks.grade">
            <option value="">全部</option>
            <option v-for="item in catalog?.grades ?? []" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
      </div>
      <div v-if="quickPeriod === 'CUSTOM'" class="stat__dates">
        <BusinessDateField v-model="picks.date_from" label="起始业务夜" placeholder="选择起始日期" />
        <BusinessDateField v-model="picks.date_to" label="结束业务夜" placeholder="选择结束日期" />
      </div>

      <div class="stat__actions">
        <button class="terminal__submit" type="button" :disabled="queryState === 'loading'" @click="query">
          {{ queryState === 'loading' ? '统计中……' : '查询' }}
        </button>
        <button class="panel__reload" type="button" @click="reset">恢复默认</button>
        <span v-if="quickPeriod === 'CUSTOM'" class="manual__hint">日期留空时统计最近 {{ DEFAULT_RANGE_NIGHTS }} 个业务夜，实际区间以结果为准。</span>
      </div>

      <p v-if="queryState === 'loading'" class="panel__line">读取中……</p>
      <div v-else-if="queryState === 'denied'" class="panel__placeholder panel__placeholder--denied">
        <p class="panel__placeholderTitle">后端已拒绝此操作。</p>
        <p class="panel__placeholderNote">{{ queryNotice }}</p>
      </div>
      <div v-else-if="queryState === 'error'" class="panel__placeholder panel__placeholder--error">
        <p class="panel__placeholderTitle">统计失败</p>
        <p class="panel__placeholderNote">{{ queryNotice }}</p>
      </div>

      <p v-else-if="queryState === 'idle'" class="panel__line">尚未查询。选择条件后点击“查询”；全部条件为“全部”也需主动查询。</p>
      <template v-else-if="result">
        <p class="panel__line stat__summary">
          业务夜 {{ formatDate(result.range.date_from) }} 至 {{ formatDate(result.range.date_to) }} · {{ activeFilterText }}
        </p>

        <div v-if="quickSummary?.period === 'DAY'" class="stat__cards">
          <div class="stat__card"><span class="stat__label">昨夜晚归人数</span><strong class="stat__value">{{ quickSummary.yesterday_returned_people }}</strong><span class="stat__sub">{{ formatDate(quickSummary.date_to) }} 业务夜 · 正式返宿</span></div>
          <div class="stat__card"><span class="stat__label">今夜已预约人数</span><strong class="stat__value">{{ quickSummary.today_reserved_people }}</strong><span class="stat__sub">{{ formatDate(quickSummary.current_service_date) }} 业务夜 · 非取消预约</span></div>
        </div>
        <div v-else class="stat__cards">
          <div class="stat__card">
            <span class="stat__label">晚归人数</span>
            <strong class="stat__value">{{ result.totals.people }}</strong>
            <span class="stat__sub">去重到人，在册 {{ result.totals.enrolled }} 人</span>
          </div>
          <div class="stat__card">
            <span class="stat__label">晚归夜数</span>
            <strong class="stat__value">{{ result.totals.nights }}</strong>
            <span class="stat__sub">一人多夜按夜累计</span>
          </div>
          <div class="stat__card">
            <span class="stat__label">返宿次数</span>
            <strong class="stat__value">{{ result.totals.returns }}</strong>
            <span class="stat__sub">
              扫码 {{ result.totals.qr_returns }} · 人工补录 {{ result.totals.manual_returns }}
            </span>
          </div>
        </div>

        <p v-for="gap in result.data_gaps" :key="gap" class="panel__line stat__gap">
          数据缺口：{{ GAP_TEXT[gap] ?? gap }}
        </p>

        <StatisticsTrend :days="result.by_day" :range="result.range" />
        <table class="stat__table">
          <caption class="stat__caption">{{ quickSummary?.period === 'DAY' ? '昨夜正式晚归按宿舍区分组（预约列也属昨夜）' : '按宿舍区分组' }}</caption>
          <thead>
            <tr>
              <th>片区</th>
              <th>晚归人数</th>
              <th>晚归夜数</th>
              <th>返宿次数</th>
              <th>扫码</th>
              <th>人工补录</th>
              <th>在册</th>
              <th>预约</th>
              <th>未确认</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in result.rows" :key="row.label">
              <td>{{ row.label }} <button v-if="row.value" class="panel__reload" @click="selectedPark = selectedPark === String(row.value) ? '' : String(row.value)">{{ selectedPark === String(row.value) ? '收起楼栋' : '查看楼栋' }}</button></td>
              <td>{{ row.people }}</td>
              <td>{{ row.nights }}</td>
              <td>{{ row.returns }}</td>
              <td>{{ row.qr_returns }}</td>
              <td>{{ row.manual_returns }}</td>
              <td>{{ row.enrolled }}</td>
              <td>{{ row.reservations ?? '—' }}</td>
              <td>{{ row.unconfirmed ?? '—' }}</td>
            </tr>
            <tr v-if="!result.rows.length">
              <td colspan="9">区间内没有晚归事实。</td>
            </tr>
          </tbody>
        </table>

        <StatisticsBreakdown v-if="selectedPark" :park-id="selectedPark" :park-name="result.rows.find(r=>String(r.value)===selectedPark)?.label ?? selectedPark" :query="detailQuery" />

        <table class="stat__table">
          <caption class="stat__caption">逐夜明细</caption>
          <thead>
            <tr>
              <th>业务夜</th>
              <th>晚归人数</th>
              <th>晚归夜数</th>
              <th>返宿次数</th>
              <th>扫码</th>
              <th>人工补录</th>
              <th>在册</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="day in result.by_day" :key="day.service_date">
              <td>{{ formatDate(day.service_date) }}</td>
              <td>{{ day.people }}</td>
              <td>{{ day.nights }}</td>
              <td>{{ day.returns }}</td>
              <td>{{ day.qr_returns }}</td>
              <td>{{ day.manual_returns }}</td>
              <td>{{ day.enrolled }}</td>
            </tr>
            <tr v-if="!result.by_day.length">
              <td colspan="7">区间内没有晚归事实。</td>
            </tr>
          </tbody>
        </table>
      </template>
    </section>

    <section class="panel">
      <header class="panel__head">
        <h2>受控导出</h2>
        <div v-if="canExport" class="stat__actions">
          <button class="panel__reload" type="button" :aria-expanded="showExports" aria-controls="export-records" @click="toggleExports">{{ showExports ? '收起导出记录' : '导出记录' }}</button>
          <button v-if="showExports" class="panel__reload" type="button" @click="restartPolling">刷新任务</button>
        </div>
      </header>

      <p v-if="!canExport" class="panel__line">
        导出字段另设权限（<code>export:create</code>），当前账号未被授予，页面不显示发起入口。
      </p>

      <template v-else>
        <p class="panel__line">
          导出的是上面这份统计的聚合结果，不含学生明细与联系方式；文件到期后内容清空、任务留档。
        </p>

        <div class="stat__actions">
          <button class="terminal__submit" type="button" :disabled="submitting || !result" @click="requestExport">
            {{ submitting ? '排队中……' : '按当前口径导出 CSV' }}
          </button>
        </div>

        <p v-if="exportNotice" class="panel__line stat__gap">{{ exportNotice }}</p>
        <p v-if="exportError" class="panel__line stat__error">{{ exportError }}</p>

        <div v-if="showExports" id="export-records">
        <ul v-if="jobs.length" class="stat__jobs">
          <li v-for="job in jobs" :key="job.export_id" class="stat__job">
            <div class="stat__jobMain">
              <span class="tonight__name">{{ job.file_name ?? '（尚未生成文件）' }}</span>
              <span class="tonight__meta">
                {{ job.status === 'DONE' ? `${job.row_count} 行 · 有效期至 ${shownAt(job.expires_at)}` : job.error ?? '等待后台生成' }}
                · 发起于 {{ shownAt(job.created_at) }}
              </span>
            </div>
            <div class="tonight__side">
              <span class="records__pill" :data-status="job.status">{{ job.status === 'DONE' && !job.downloadable ? '已过期' : STATUS_LABEL[job.status] }}</span>
              <button
                v-if="job.downloadable"
                class="panel__reload"
                type="button"
                @click="download(job)"
              >
                下载
              </button>
              <button v-if="session.can('export:delete')" class="panel__reload" type="button" :disabled="!!deletingExport" @click="removeExport(job)">{{ deletingExport === job.export_id ? '删除中……' : '删除' }}</button>
            </div>
          </li>
        </ul>
        <div v-else class="panel__placeholder">
          <p class="panel__placeholderTitle">还没有导出任务。</p>
          <p class="panel__placeholderNote">选好口径后点「按当前口径导出 CSV」。</p>
        </div>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.stat__periods { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.stat__periods button[aria-pressed='true'] { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
.stat__dates { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; max-width: 640px; margin-top: 16px; }
@media (max-width: 650px) { .stat__dates { grid-template-columns: 1fr; } }
</style>

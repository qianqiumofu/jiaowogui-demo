<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import { ApiRequestError, api } from '@/shared/api/client'
import type { ExportJob, StatisticsFilters, StatisticsResult } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()

const ATTRIBUTIONS = [
  { value: 'snapshot', label: '发生时快照' },
  { value: 'current', label: '当前住宿名册' },
]
const GENDER_LABEL: Record<string, string> = { MALE: '男', FEMALE: '女' }
const SOURCE_LABEL: Record<string, string> = { QR: '扫码返宿', MANUAL: '人工补录' }
const GAP_TEXT: Record<string, string> = {
  RESERVATION_SOURCE_UNAVAILABLE:
    '「预约」与「未确认」两列的数据来源尚未落地，本页面按空值显示，不计入晚归判定。',
}

// 与后端 `app/modules/statistics/router.py::DEFAULT_RANGE_NIGHTS` 同一个取值，改那边要改这里。
const DEFAULT_RANGE_NIGHTS = 14

// 分组固定按片区：学院/年级/性别已经能做筛选，全校合计在上方三张卡片里，
// 逐夜明细在下面单独一张表，都不需要再靠一个下拉切换。
const GROUP_BY = 'park'

const EMPTY_PICKS = {
  college_org_id: '',
  park_org_id: '',
  building_id: '',
  grade: '',
  gender: '',
  return_source: '',
  date_from: '',
  date_to: '',
}

type PickKey = keyof typeof EMPTY_PICKS

const catalog = ref<StatisticsFilters | null>(null)
const catalogState = ref<'loading' | 'ready' | 'error'>('loading')
const catalogError = ref('')
const picks = ref({ ...EMPTY_PICKS })
const attribution = ref('snapshot')
const result = ref<StatisticsResult | null>(null)
const queryState = ref<'loading' | 'ready' | 'denied' | 'error'>('loading')
const queryNotice = ref('')

const params = computed(() => {
  const query: Record<string, string> = { group_by: GROUP_BY, attribution: attribution.value }
  for (const [key, value] of Object.entries(picks.value)) if (value) query[key] = value
  return query
})

// 导出契约要求显式区间，统计则允许留空取默认；补成屏幕上这份区间，两边才不会各算一段。
const exportParams = computed(() => {
  const query: Record<string, string> = { ...params.value }
  if (!query.date_from) query.date_from = result.value?.range.date_from ?? ''
  if (!query.date_to) query.date_to = result.value?.range.date_to ?? ''
  return query
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
  ['gender', '性别'],
  ['return_source', '来源'],
]

// 用后端回传的 filters，说明的就是表格里这份结果，改了下拉还没重算时不会先变。
const activeFilterText = computed(() => {
  const applied = result.value?.filters ?? {}
  const names = FILTER_ORDER.filter(([key]) => applied[key]).map(
    ([key, label]) => `${label}=${labelOf(key, applied[key])}`,
  )
  return names.length ? names.join(' · ') : '无筛选（全校）'
})

function labelOf(key: PickKey, value: string): string {
  if (key === 'gender') return GENDER_LABEL[value] ?? value
  if (key === 'return_source') return SOURCE_LABEL[value] ?? value
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

async function query() {
  queryState.value = 'loading'
  queryNotice.value = ''
  try {
    result.value = await api.statistics(params.value)
    queryState.value = 'ready'
  } catch (cause) {
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
  attribution.value = 'snapshot'
  query()
}

const jobs = ref<ExportJob[]>([])
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
  if (submitting.value) return
  submitting.value = true
  exportNotice.value = ''
  exportError.value = ''
  try {
    await api.createExport(exportParams.value, exportKey())
    await refreshJobs()
  } catch (cause) {
    exportError.value = describeError(cause)
  } finally {
    submitting.value = false
  }
}

// 幂等键要能区分口径，连点数两次的重复提交才只命中同一份文件；
// 用 FNV-1a 压成短串，避免超过契约里 128 字符的限制。
function exportKey(): string {
  const canonical = Object.entries(exportParams.value)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value ?? ''}`)
    .join('&')
  let hash = 0x811c9dc5
  for (const char of canonical) {
    hash ^= char.codePointAt(0) as number
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return `web:${session.context?.user_id ?? ''}:${hash.toString(16)}`
}

async function refreshJobs() {
  try {
    jobs.value = (await api.myExports()).items
    if (jobs.value.some((job) => job.status === 'PENDING' || job.status === 'RUNNING')) schedulePoll()
  } catch (cause) {
    exportError.value = describeError(cause)
  }
}

// worker 未启动时任务停在排队：轮询有上限，超时后给出提示而不是无限转圈。
function schedulePoll() {
  if (timer) clearTimeout(timer)
  if (pollsLeft <= 0) {
    exportNotice.value = '任务仍在排队。导出由后台 worker 渲染，请先确认 worker 已启动，再点「刷新任务」。'
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
    const url = URL.createObjectURL(new Blob([file.text], { type: 'text/csv;charset=utf-8' }))
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
  await query()
  if (canExport.value) {
    pollsLeft = 10
    await refreshJobs()
  }
})

onUnmounted(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>全校晚归统计</h2>
        <button class="panel__reload" type="button" :disabled="queryState === 'loading'" @click="query">
          重新统计
        </button>
      </header>
      <p class="panel__line">
        按学院、片区、楼栋、年级、性别筛选全校晚归；人数、晚归夜数与返宿次数分开计算，互不相加。
      </p>

      <p v-if="catalogState === 'error'" class="stat__gap">
        筛选选项读不到（{{ catalogError }}），下面六个下拉此刻只剩「全部」，不是校区里真的只有一个学院或一个片区。
        后端未启动、或进程版本过旧没有 <code>GET /statistics/filters</code> 时就是这个样子。
        <button class="panel__reload" type="button" @click="loadCatalog">重试读取</button>
      </p>
      <p v-else-if="catalogState === 'loading'" class="panel__line">筛选选项读取中……</p>

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
          <span>片区</span>
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
          <span>年级</span>
          <select v-model="picks.grade">
            <option value="">全部</option>
            <option v-for="item in catalog?.grades ?? []" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
        <label class="stat__field">
          <span>性别</span>
          <select v-model="picks.gender">
            <option value="">全部</option>
            <option v-for="item in catalog?.genders ?? []" :key="item" :value="item">
              {{ GENDER_LABEL[item] }}
            </option>
          </select>
        </label>
        <label class="stat__field">
          <span>返宿来源</span>
          <select v-model="picks.return_source">
            <option value="">全部</option>
            <option v-for="item in catalog?.return_sources ?? []" :key="item" :value="item">
              {{ SOURCE_LABEL[item] }}
            </option>
          </select>
        </label>
        <label class="stat__field">
          <span>起始业务夜</span>
          <input v-model="picks.date_from" type="date" />
        </label>
        <label class="stat__field">
          <span>结束业务夜</span>
          <input v-model="picks.date_to" type="date" />
        </label>
        <label class="stat__field">
          <span>归属口径</span>
          <select v-model="attribution">
            <option v-for="item in ATTRIBUTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
      </div>

      <div class="stat__actions">
        <button class="terminal__submit" type="button" :disabled="queryState === 'loading'" @click="query">
          {{ queryState === 'loading' ? '统计中……' : '按此口径统计' }}
        </button>
        <button class="panel__reload" type="button" @click="reset">恢复默认</button>
        <span class="manual__hint">日期留空时统计最近 {{ DEFAULT_RANGE_NIGHTS }} 个业务夜，实际区间以结果为准。</span>
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

      <template v-else-if="result">
        <p class="panel__line stat__summary">
          业务夜 {{ result.range.date_from }} 至 {{ result.range.date_to }} · {{ activeFilterText }} ·
          归属口径：{{ ATTRIBUTIONS.find((item) => item.value === result?.attribution)?.label }}
        </p>

        <div class="stat__cards">
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

        <table class="stat__table">
          <caption class="stat__caption">按片区分组</caption>
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
              <td>{{ row.label }}</td>
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
              <td>{{ day.service_date }}</td>
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
        <button class="panel__reload" type="button" @click="refreshJobs">刷新任务</button>
      </header>

      <p v-if="!canExport" class="panel__line">
        导出字段另设权限（<code>export:create</code>），当前账号未被授予，页面不显示发起入口。
      </p>

      <template v-else>
        <p class="panel__line">
          导出的是上面这份统计的聚合结果，不含学生明细与联系方式；文件到期后内容清空、任务留档。
        </p>

        <div class="stat__actions">
          <button class="terminal__submit" type="button" :disabled="submitting" @click="requestExport">
            {{ submitting ? '排队中……' : '按当前口径导出 CSV' }}
          </button>
        </div>

        <p v-if="exportNotice" class="panel__line stat__gap">{{ exportNotice }}</p>
        <p v-if="exportError" class="panel__line stat__error">{{ exportError }}</p>

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
              <span class="records__pill" :data-status="job.status">{{ STATUS_LABEL[job.status] }}</span>
              <button
                v-if="job.downloadable"
                class="panel__reload"
                type="button"
                @click="download(job)"
              >
                下载
              </button>
            </div>
          </li>
        </ul>
        <div v-else class="panel__placeholder">
          <p class="panel__placeholderTitle">还没有导出任务。</p>
          <p class="panel__placeholderNote">选好口径后点「按当前口径导出 CSV」。</p>
        </div>
      </template>
    </section>
  </div>
</template>

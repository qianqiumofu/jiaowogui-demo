<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/shared/api/client'
import { describeError } from '@/shared/stores/session'
import type { SchoolOverview, StatisticsFilters } from '@/shared/api/types'
import StatisticsStudentList from '../components/StatisticsStudentList.vue'

type Period = 'DAY' | 'WEEK' | 'MONTH'
const period = ref<Period>('DAY'), overview = ref<SchoolOverview | null>(null)
const options = ref<StatisticsFilters | null>(null), loading = ref(false), error = ref('')
const generation = ref(0)
let requestSequence = 0
async function load(next = period.value) {
  const sequence = ++requestSequence
  period.value = next; generation.value++
  overview.value = null; error.value = ''; loading.value = true
  try {
    const [summary, catalog] = await Promise.all([api.schoolOverview(next), api.schoolStatisticsOptions()])
    if (sequence !== requestSequence) return
    overview.value = summary; options.value = catalog
  } catch (cause) {
    if (sequence === requestSequence) error.value = describeError(cause)
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}
onMounted(() => load())
</script>

<template><div class="stack school-statistics">
  <section class="panel"><h1>查看晚归情况</h1><p>全校授权范围 · 人数汇总与名单查询分开显示</p>
    <div class="period-tabs" aria-label="统计周期"><button v-for="tab in ([['DAY','日统计'],['WEEK','周统计'],['MONTH','月统计']] as const)" :key="tab[0]" :aria-pressed="period === tab[0]" @click="load(tab[0])">{{ tab[1] }}</button><button :disabled="loading" @click="load()">刷新统计</button></div>
    <p v-if="loading" role="status">正在读取人数统计……</p><p v-if="error" role="alert">{{ error }}</p>
    <template v-if="overview"><p>当前业务日：{{ overview.current_service_date }}；{{ period === 'DAY' ? '昨日业务夜' : '统计区间' }}：{{ overview.date_from }} 至 {{ overview.date_to }}。</p>
      <p v-if="period !== 'DAY'">{{ period === 'WEEK' ? '按昨日所在自然周，从周一统计至昨日。' : '按昨日所在自然月，从月初统计至昨日。' }}</p>
    </template>
  </section>
  <template v-if="overview && options">
    <template v-if="period === 'DAY'">
      <section class="panel"><h2>昨日晚归人数</h2><p class="metric">{{ overview.yesterday_returned_people }} <span>人</span></p><p>{{ overview.date_to }} 业务夜有正式返宿记录的去重学生人数。</p></section>
      <StatisticsStudentList :key="`returned-${generation}`" title="昨日晚归学生" :period="period" dataset="RETURNED" :options="options" />
      <section class="panel"><h2>今日已预约人数</h2><p class="metric">{{ overview.today_reserved_people }} <span>人</span></p><p>{{ overview.current_service_date }} 业务夜的非取消预约，预约人数不代表已晚归。</p></section>
      <StatisticsStudentList :key="`reserved-${generation}`" title="今日已预约学生" :period="period" dataset="RESERVED" :options="options" />
    </template>
    <template v-else>
      <section class="panel"><h2>{{ period === 'WEEK' ? '本周' : '本月' }}晚归统计</h2><div class="totals"><div><strong>{{ overview.returned_people }}</strong><span>晚归人数</span></div><div><strong>{{ overview.returned_nights }}</strong><span>晚归总夜数（学生 × 夜）</span></div><div><strong>{{ overview.repeated_people }}</strong><span>多次晚归人数</span></div></div></section>
      <StatisticsStudentList :key="`all-${generation}`" title="晚归学生名单" :period="period" dataset="RETURNED" :options="options" />
      <section class="panel"><h2>多次晚归同学</h2><p>周期内正式晚归至少 {{ overview.repeat_min_nights }} 夜：共 {{ overview.repeated_people }} 人。此项仅作统计展示。</p></section>
      <StatisticsStudentList :key="`repeated-${generation}`" title="多次晚归学生专栏" :period="period" dataset="REPEATED" :options="options" />
    </template>
    <section class="panel"><h2>统计口径</h2><p>晚归只计二维码成功通行或人工补录形成的正式返宿记录；领码、申请、未确认返宿不计晚归。所有日期由服务端按业务夜判定，06:00 切换业务日。</p><p>学院、年级取目录登记；宿舍区与楼栋按发生业务夜归属筛选。跨夜名单在筛选后汇总晚归夜数，住宿列显示最近匹配业务夜的归属。</p><p>展开名单不会自动查询，修改筛选或统计周期会清空已显示的名单，需重新点击“查询”。</p></section>
  </template>
</div></template>

<style scoped>
.period-tabs { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0; }
button { border: 1px solid var(--line); border-radius: 10px; padding: 10px 18px; color: var(--ink); background: var(--accent-soft); cursor: pointer; }
button[aria-pressed="true"] { background: var(--accent); color: white; }
button:disabled { opacity: .45; cursor: not-allowed; }
.metric { font-size: 42px; font-weight: 700; margin: 12px 0; }
.metric span { font-size: 16px; font-weight: 400; }
.totals { display: flex; flex-wrap: wrap; gap: 36px; margin: 20px 0; }
.totals div { display: flex; flex-direction: column; gap: 8px; }
.totals strong { font-size: 32px; }
</style>

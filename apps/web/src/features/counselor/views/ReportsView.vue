<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'

import { RETURN_STATE_TEXT } from '@/features/counselor/labels'
import { ApiRequestError, api } from '@/shared/api/client'
import { describeError,useSessionStore } from '@/shared/stores/session'
import type { DailyReport, WeeklyReport } from '@/shared/api/types'

const session=useSessionStore()
const subscription=ref({daily:false,weekly:false}), subMessage=ref('')
async function saveSubscription(){try{subscription.value=await api.saveSubscription(subscription.value);subMessage.value='订阅已保存；普通报告与风险投递相互独立。'}catch(e){subMessage.value=describeError(e)}}
type Kind = 'daily' | 'weekly'

const kind = ref<Kind>('daily')
const daily = ref<DailyReport | null>(null)
const weekly = ref<WeeklyReport | null>(null)
// 留空时由服务端决定前一业务夜；切换查询条件只清空结果，不自动加载。
const picked = ref('')
const latest = ref('')
const loading = ref(false)
const queried = ref(false)
let sequence = 0
function invalidate() { sequence++; daily.value = null; weekly.value = null; queried.value = false; loading.value = false; failure.value = '' }
watch([kind, picked], invalidate, { flush: 'sync' })
onBeforeUnmount(invalidate)
const failure = ref('')

const chips = computed(() => {
  const totals = kind.value === 'daily' ? daily.value?.totals : weekly.value?.totals
  if (!totals) return []
  return [
    { label: '学生', value: totals.students },
    { label: '业务夜', value: totals.nights },
    { label: '未确认返宿', value: totals.unconfirmed },
  ]
})

const notes = computed<string[]>(() =>
  kind.value === 'daily' ? (daily.value?.caliber_notes ?? []) : (weekly.value?.caliber_notes ?? []),
)

function nightText(value: string): string {
  return value.slice(5, 10).replace('-', '/') + ' 夜'
}

function timeText(value: string): string {
  return value.slice(11, 16)
}

async function load() {
  const requestSequence = ++sequence
  const requestedKind = kind.value
  loading.value = true
  failure.value = ''
  queried.value = false
  daily.value = null; weekly.value = null
  const date = picked.value || undefined
  try {
    if (requestedKind === 'daily') {
      const body = await api.dailyReport(date)
      if (requestSequence !== sequence) return
      daily.value = body
    } else {
      const body = await api.weeklyReport(date)
      if (requestSequence !== sequence) return
      weekly.value = body
    }
    queried.value = true
  } catch (cause) {
    if (requestSequence !== sequence) return
    failure.value =
      cause instanceof ApiRequestError ? `${cause.code}：${cause.message}` : '报告读取失败。'
  } finally {
    if (requestSequence === sequence) loading.value = false
  }
}

async function switchTo(next: Kind) {
  if (kind.value === next) return
  kind.value = next
}

async function backToLastFinishedNight() {
  picked.value = ''
  invalidate()
}

onMounted(async () => {
  try {
    latest.value = (await api.clock()).service_date
  } catch {
    // 时钟读不到只影响日期控件的上界，服务端仍然会拒绝越界的查询。
  }
  if(session.can('report:subscribe')) { try { subscription.value=await api.subscription() } catch(e) { subMessage.value=describeError(e) } }
})
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>{{ kind === 'daily' ? '前一晚日报' : '最近一周周报' }}</h2>
        <button class="panel__reload" type="button" :disabled="loading" @click="load">查询</button>
      </header>

      <div class="rep__tools">
        <div class="rep__tabs">
          <button
            class="rep__tab"
            :class="{ 'rep__tab--on': kind === 'daily' }"
            type="button"
            @click="switchTo('daily')"
          >
            当夜明细
          </button>
          <button
            class="rep__tab"
            :class="{ 'rep__tab--on': kind === 'weekly' }"
            type="button"
            @click="switchTo('weekly')"
          >
            逐夜汇总
          </button>
        </div>
        <label class="rep__date">
          <span>业务日</span>
          <input v-model="picked" type="date" :max="latest || undefined"  />
        </label>
        <button class="rep__reset" type="button" @click="backToLastFinishedNight">回到前一晚</button>
      </div>

      <p v-if="loading" class="panel__line">读取中……</p>
      <p v-else-if="failure" class="resv__notice resv__notice--bad">{{ failure }}</p>

      <p v-else-if="!queried" class="panel__line">尚未查询。选择业务日与日报或周报后点击“查询”；留空默认查看前一晚。</p>
      <template v-else>
        <p class="panel__line">{{ (kind === 'daily' ? daily : weekly)?.scope_note }}</p>

        <ul class="rep__chips">
          <li v-for="chip in chips" :key="chip.label" class="rep__chip">
            <span class="rep__chipLabel">{{ chip.label }}</span>
            <strong class="rep__chipValue">{{ chip.value }}</strong>
          </li>
        </ul>

        <ul v-if="kind === 'daily' && daily" class="rep__list">
          <li v-for="item in daily.items" :key="item.student_id" class="rep__row" :data-status="item.status">
            <p class="rep__name">{{ item.school_id }} · {{ item.display_name }}</p>
            <p class="rep__meta">
              <span>计划 {{ timeText(item.planned_return_at) }} 前回</span>
              <span class="rep__state">{{ RETURN_STATE_TEXT[item.status] ?? item.status }}</span>
            </p>
          </li>
          <li v-if="!daily.items.length" class="panel__placeholderNote">当晚没有预约记录。</li>
        </ul>

        <ul v-else-if="kind === 'weekly' && weekly" class="rep__list">
          <li
            v-for="night in weekly.nights"
            :key="night.service_date"
            class="rep__row"
            :class="{ 'rep__row--empty': night.total === 0 }"
          >
            <p class="rep__name">{{ nightText(night.service_date) }}</p>
            <p class="rep__meta">
              <span>预约 {{ night.total }} 人</span>
              <span class="rep__state">未确认 {{ night.unconfirmed }} 人</span>
            </p>
          </li>
        </ul>

        <p v-if="kind === 'daily' && daily" class="panel__line">
          门禁时段 {{ daily.night_window[0].slice(5, 16) }} 至 {{ daily.night_window[1].slice(5, 16) }}，
          由服务端判定。
        </p>

        <ul class="rep__notes">
          <li v-for="note in notes" :key="note">{{ note }}</li>
        </ul>
      </template>

      <section v-if="session.can('report:subscribe')"><h3>自动报告订阅</h3><label><input v-model="subscription.daily" type="checkbox">日报（次日 08:30，演示配置）</label><label><input v-model="subscription.weekly" type="checkbox">周报（周一 09:00，演示配置）</label><button @click="saveSubscription">保存订阅</button><p role="status">{{ subMessage }}</p><p>由 worker 自动入队并投递到模拟收件箱，不发送真实邮件。</p></section>
    </section>
  </div>
</template>

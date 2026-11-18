<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { RETURN_STATE_TEXT } from '@/features/counselor/labels'
import { ApiRequestError, api } from '@/shared/api/client'
import type { DailyReport, WeeklyReport } from '@/shared/api/types'

type Kind = 'daily' | 'weekly'

const kind = ref<Kind>('daily')
const daily = ref<DailyReport | null>(null)
const weekly = ref<WeeklyReport | null>(null)
// 空字符串＝让服务端自己决定看哪一晚；读回来后把服务端的判定回填到控件，前端不推算业务日。
const picked = ref('')
const latest = ref('')
const loading = ref(true)
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
  loading.value = true
  failure.value = ''
  const date = picked.value || undefined
  try {
    if (kind.value === 'daily') {
      const body = await api.dailyReport(date)
      daily.value = body
      picked.value = body.service_date
    } else {
      const body = await api.weeklyReport(date)
      weekly.value = body
      picked.value = body.service_date
    }
  } catch (cause) {
    failure.value =
      cause instanceof ApiRequestError ? `${cause.code}：${cause.message}` : '报告读取失败。'
  } finally {
    loading.value = false
  }
}

async function switchTo(next: Kind) {
  if (kind.value === next) return
  kind.value = next
  await load()
}

async function backToLastFinishedNight() {
  picked.value = ''
  await load()
}

onMounted(async () => {
  try {
    latest.value = (await api.clock()).service_date
  } catch {
    // 时钟读不到只影响日期控件的上界，服务端仍然会拒绝越界的查询。
  }
  await load()
})
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>{{ kind === 'daily' ? '前一晚日报' : '最近一周周报' }}</h2>
        <button class="panel__reload" type="button" :disabled="loading" @click="load">重新读取</button>
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
          <input v-model="picked" type="date" :max="latest || undefined" @change="load" />
        </label>
        <button class="rep__reset" type="button" @click="backToLastFinishedNight">回到前一晚</button>
      </div>

      <p v-if="loading" class="panel__line">读取中……</p>
      <p v-else-if="failure" class="resv__notice resv__notice--bad">{{ failure }}</p>

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

      <p class="panel__stage">订阅与邮件投递时刻仍为占位（M4）。</p>
    </section>
  </div>
</template>

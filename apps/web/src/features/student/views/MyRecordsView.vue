<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import RevisionTimeline from '@/features/student/components/RevisionTimeline.vue'
import { STATUS_TEXT, VERIFICATION_TEXT } from '@/features/student/labels'
import { ApiRequestError, api } from '@/shared/api/client'
import type { ClockState, Reservation, ReservationRevision } from '@/shared/api/types'
import RecordsView from '@/features/shared/views/RecordsView.vue'

const nights = ref<Reservation[]>([])
const clock = ref<ClockState | null>(null)
const loading = ref(true)
const failure = ref('')
const openedId = ref<string | null>(null)
const timelines = ref<Record<string, ReservationRevision[]>>({})

// 今夜标记只比对服务端返回的 service_date，不自行推算跨 06:00 的归属。
const tonightDate = computed(() => clock.value?.service_date ?? '')

function nightLabel(item: Reservation): string {
  return `${item.service_date.slice(5, 10)} 夜`
}

function gateText(item: Reservation): string {
  if (item.status !== 'ACTIVE') return ''
  return VERIFICATION_TEXT[item.verification.state] ?? ''
}

async function load() {
  loading.value = true
  failure.value = ''
  try {
    const [list, state] = await Promise.all([api.reservations(), api.clock()])
    nights.value = list.items
    clock.value = state
  } catch (cause) {
    nights.value = []
    failure.value = cause instanceof ApiRequestError ? `${cause.code}：${cause.message}` : '记录读取失败。'
  } finally {
    loading.value = false
  }
}

async function toggleTimeline(id: string) {
  failure.value = ''
  if (openedId.value === id) {
    openedId.value = null
    return
  }
  openedId.value = id
  if (timelines.value[id]) return
  try {
    timelines.value = { ...timelines.value, [id]: (await api.reservationRevisions(id)).items }
  } catch (cause) {
    // 失败时不缓存空数组，下次展开还能重取。
    const cached = { ...timelines.value }
    delete cached[id]
    timelines.value = cached
    failure.value = cause instanceof ApiRequestError ? `${cause.code}：${cause.message}` : '留痕读取失败。'
  }
}

onMounted(load)
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>我的晚归预约</h2>
        <button class="panel__reload" type="button" :disabled="loading" @click="load">重新读取</button>
      </header>
      <p class="panel__line">一晚一条，按业务夜从近到远排列；改期、取消与恢复都留痕。</p>

      <p v-if="loading" class="panel__line">读取中……</p>
      <p v-if="failure" class="resv__notice resv__notice--bad">{{ failure }}</p>

      <div v-if="!loading && !nights.length && !failure" class="panel__placeholder">
        <p class="panel__placeholderTitle">还没有预约记录。</p>
        <p class="panel__placeholderNote">在「晚归预约」页提交即可，不需要审批。</p>
      </div>

      <ul v-if="nights.length" class="hist__list">
        <li v-for="item in nights" :key="item.id" class="hist__row" :data-status="item.status">
          <p class="hist__night">
            {{ nightLabel(item) }}
            <span v-if="item.service_date === tonightDate" class="hist__tag">本夜</span>
          </p>
          <p class="hist__meta">
            <span class="hist__state">{{ STATUS_TEXT[item.status] ?? item.status }}</span>
            <span class="hist__time">{{ item.planned_return_at.slice(11, 16) }} 前回</span>
            <span class="hist__version">第 {{ item.version }} 版</span>
            <span v-if="gateText(item)" class="hist__gate">{{ gateText(item) }}</span>
          </p>
          <button class="hist__toggle" type="button" @click="toggleTimeline(item.id)">
            {{ openedId === item.id ? '收起留痕' : '展开留痕' }}
          </button>
          <RevisionTimeline
            v-if="openedId === item.id && timelines[item.id]"
            :items="timelines[item.id]"
            class="hist__timeline"
          />
          <p v-else-if="openedId === item.id" class="panel__line">留痕读取中……</p>
        </li>
      </ul>
    </section>

    <RecordsView :self-view="true" />
  </div>
</template>

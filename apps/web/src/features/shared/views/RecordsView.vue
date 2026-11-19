<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ReturnDetails from '@/features/shared/components/ReturnDetails.vue'
const props=defineProps<{selfView?:boolean}>()

import { ApiRequestError, api } from '@/shared/api/client'
import type { ReturnRecordItem, ReturnRecords } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()

const state = ref<'loading' | 'ready' | 'denied' | 'error'>('loading')
const notice = ref('')
const data = ref<ReturnRecords | null>(null)
const serviceDate = ref('')
const activeBuilding = ref('')

const buildings = computed(() => session.context?.scope.building_ids ?? [])
const items = computed<ReturnRecordItem[]>(() => data.value?.items ?? [])

const PASS_LABEL: Record<string, string> = {
  ISSUED: '待通行',
  CONSUMED: '已核销',
  EXPIRED: '已过期',
  REVOKED: '已作废',
}

function passLabel(item: ReturnRecordItem): string {
  return item.pass_status ? PASS_LABEL[item.pass_status] : '无二维码'
}

async function load() {
  state.value = 'loading'
  notice.value = ''
  try {
    data.value = await (props.selfView ? api.ownReturnRecords : api.returnRecords)({
      serviceDate: serviceDate.value || undefined,
      buildingId: activeBuilding.value || undefined,
    })
    serviceDate.value = data.value.service_date
    state.value = 'ready'
  } catch (cause) {
    data.value = null
    if (cause instanceof ApiRequestError) {
      state.value =
        cause.code.startsWith('FORBIDDEN') ||
        cause.code === 'SCOPE_UNRESOLVED' ||
        cause.code === 'OUT_OF_SCOPE'
          ? 'denied'
          : 'error'
      notice.value = describeError(cause)
    } else {
      state.value = 'error'
      notice.value = String(cause)
    }
  }
}

function shiftNight(days: number) {
  const next = new Date(`${serviceDate.value}T12:00:00`)
  next.setDate(next.getDate() + days)
  serviceDate.value = next.toISOString().slice(0, 10)
  load()
}

function clockTime(value?: string | null): string {
  return value ? value.slice(11, 19) : '—'
}

onMounted(() => {
  activeBuilding.value = buildings.value[0] ?? ''
  load()
})
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>返宿记录</h2>
        <div class="records__actions">
          <button class="panel__reload" type="button" @click="shiftNight(-1)">前一晚</button>
          <button class="panel__reload" type="button" @click="shiftNight(1)">后一晚</button>
          <button class="panel__reload" type="button" @click="serviceDate = ''; load()">
            回到今晚
          </button>
          <button class="panel__reload" type="button" @click="load">重新读取</button>
        </div>
      </header>

      <nav v-if="buildings.length > 1" class="tonight__tabs">
        <button
          v-for="building in buildings"
          :key="building"
          class="tonight__tab"
          :class="{ 'tonight__tab--active': building === activeBuilding }"
          type="button"
          @click="activeBuilding = building; load()"
        >
          {{ building }}
        </button>
      </nav>

      <p v-if="state === 'ready' && data" class="panel__line">
        业务夜 {{ data.service_date }} ·
        已签发 {{ data.counters.issued }} · 已核销 {{ data.counters.consumed }} ·
        已过期 {{ data.counters.expired }} · 已作废 {{ data.counters.revoked }} ·
        已返宿 {{ data.counters.returned }} 人
      </p>

      <p v-if="state === 'loading'" class="panel__line">读取中……</p>
      <div v-else-if="state === 'denied'" class="panel__placeholder panel__placeholder--denied">
        <p class="panel__placeholderTitle">后端已拒绝此操作。</p>
        <p class="panel__placeholderNote">{{ notice }}</p>
      </div>
      <div v-else-if="state === 'error'" class="panel__placeholder panel__placeholder--error">
        <p class="panel__placeholderTitle">读取失败</p>
        <p class="panel__placeholderNote">{{ notice }}</p>
      </div>
      <div v-else-if="!items.length" class="panel__placeholder">
        <p class="panel__placeholderTitle">这一夜没有返宿记录。</p>
        <p class="panel__placeholderNote">
          06:00 之后名单切到次夜，前一晚的二维码使用与返宿都回到本页按业务夜查询。
        </p>
      </div>

      <ul v-else class="records__list">
        <li v-for="item in items" :key="item.pass_id ?? item.return_id ?? item.student_id" class="records__row">
          <div class="records__main">
            <span class="records__name">{{ item.display_name }}</span>
            <span class="records__meta">{{ item.school_id }} · {{ item.building_id }}</span>
            <span class="records__pill" :data-pass="item.pass_status ?? 'NONE'">
              {{ passLabel(item) }}
            </span>
          </div>
          <dl class="records__grid">
            <div>
              <dt>领码时段</dt>
              <dd>{{ clockTime(item.window_start) }} – {{ clockTime(item.window_end) }}</dd>
            </div>
            <div>
              <dt>签发 / 过期</dt>
              <dd>{{ clockTime(item.issued_at) }} / {{ clockTime(item.expires_at) }}</dd>
            </div>
            <div>
              <dt>核销时间</dt>
              <dd>{{ clockTime(item.used_at) }}</dd>
            </div>
            <div>
              <dt>返宿</dt>
              <dd>
                {{ item.returned_at ? `${clockTime(item.returned_at)}（${item.return_source === 'QR' ? '二维码' : '人工补录'}）` : '未返宿' }}
              </dd>
            </div>
          </dl>
          <ReturnDetails v-if="item.return_id" :id="item.return_id" />
        </li>
      </ul>
    </section>
  </div>
</template>

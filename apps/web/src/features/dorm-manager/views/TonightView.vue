<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { ApiRequestError, api } from '@/shared/api/client'
import type { BuildingTonight, StudentContact, TonightItem } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()

const state = ref<'loading' | 'ready' | 'pending' | 'denied' | 'error'>('loading')
const notice = ref('')
const data = ref<BuildingTonight | null>(null)
const activeBuilding = ref('')
const contacts = ref<Record<string, StudentContact>>({})
const contactErrors = ref<Record<string, string>>({})

const buildings = computed(() => session.context?.scope.building_ids ?? [])
const items = computed<TonightItem[]>(() => data.value?.items ?? [])
const summaryPassed = computed(() => Boolean(data.value?.summary_generated_at))
const changedCount = computed(() => items.value.filter((item) => item.change_flag).length)

const FLAG_LABEL: Record<string, string> = {
  RESCHEDULED: '改期',
  CANCELLED: '撤销',
  ADDED_AFTER_SUMMARY: '汇总后新增',
}

async function load() {
  if (!activeBuilding.value) {
    state.value = 'denied'
    notice.value = '当前没有生效的值班或代班楼栋。'
    return
  }
  state.value = 'loading'
  notice.value = ''
  contacts.value = {}
  contactErrors.value = {}
  try {
    data.value = await api.buildingTonight(activeBuilding.value)
    state.value = 'ready'
  } catch (cause) {
    data.value = null
    if (cause instanceof ApiRequestError) {
      if (cause.code === 'NOT_IMPLEMENTED') state.value = 'pending'
      else if (cause.code.startsWith('FORBIDDEN') || cause.code === 'SCOPE_UNRESOLVED' || cause.code === 'OUT_OF_SCOPE')
        state.value = 'denied'
      else state.value = 'error'
      notice.value = describeError(cause)
    } else {
      state.value = 'error'
      notice.value = String(cause)
    }
  }
}

async function revealContact(item: TonightItem) {
  contactErrors.value = { ...contactErrors.value, [item.student_id]: '' }
  try {
    const contact = await api.studentContact(item.student_id)
    contacts.value = { ...contacts.value, [item.student_id]: contact }
  } catch (cause) {
    contactErrors.value = { ...contactErrors.value, [item.student_id]: describeError(cause) }
  }
}

function timeOf(value?: string | null): string {
  return value ? value.slice(11, 16) : '—'
}

watch(buildings, (list) => {
  if (!list.includes(activeBuilding.value)) activeBuilding.value = list[0] ?? ''
})

onMounted(() => {
  activeBuilding.value = buildings.value[0] ?? ''
  load()
})
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>今晚名单</h2>
        <button class="panel__reload" type="button" @click="load">重新读取</button>
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
        {{ summaryPassed ? `已于 ${data.summary_generated_at?.slice(11, 16)} 汇总并推送人数，本夜之后仅改期与撤销实时更新` : '等待 worker 生成 24:00 汇总；首次申请是否开放以服务端为准' }}
        <template v-if="changedCount"> · 异动 {{ changedCount }} 条</template>
        · 已通行 {{ data.counters.entered }} / 共 {{ data.counters.total }} 人
      </p>

      <p v-if="state === 'loading'" class="panel__line">读取中……</p>
      <div v-else-if="state === 'pending'" class="panel__placeholder">
        <p class="panel__placeholderTitle">该能力尚未实现。</p>
        <p class="panel__placeholderNote">B 负责，等 A 的 reservation.list_for_building 落地后即可显示。{{ notice }}</p>
      </div>
      <div v-else-if="state === 'denied'" class="panel__placeholder panel__placeholder--denied">
        <p class="panel__placeholderTitle">后端已拒绝此操作。</p>
        <p class="panel__placeholderNote">{{ notice }}</p>
      </div>
      <div v-else-if="state === 'error'" class="panel__placeholder panel__placeholder--error">
        <p class="panel__placeholderTitle">读取失败</p>
        <p class="panel__placeholderNote">{{ notice }}</p>
      </div>
      <div v-else-if="!items.length" class="panel__placeholder">
        <p class="panel__placeholderTitle">今晚本楼栋没有晚归预约。</p>
        <p class="panel__placeholderNote">接口按契约返回空列表。</p>
      </div>

      <ul v-else class="tonight__list">
        <li v-for="item in items" :key="item.student_id" class="tonight__row">
          <div class="tonight__main">
            <span class="tonight__room">{{ item.room_no }}</span>
            <span class="tonight__time">{{ timeOf(item.planned_return_at) }}</span>
            <span class="tonight__name">{{ item.display_name }}</span>
            <span class="tonight__meta">{{ item.school_id }} · {{ item.college_name }}</span>
            <span v-if="item.change_flag" class="tonight__flag" :data-flag="item.change_flag">
              【{{ FLAG_LABEL[item.change_flag] }}】
            </span>
            <span v-if="item.return_status !== 'PENDING'" class="tonight__done">
              {{ item.return_status === 'ENTERED' ? `已通行 ${timeOf(item.entered_at)}` : '人工补录已返' }}
            </span>
          </div>
          <div class="tonight__side">
            <button class="panel__reload" type="button" @click="revealContact(item)">
              {{ contacts[item.student_id] ? contacts[item.student_id]?.phone : '查看联系方式' }}
            </button>
            <p v-if="contactErrors[item.student_id]" class="tonight__contactError">
              {{ contactErrors[item.student_id] }}
            </p>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>

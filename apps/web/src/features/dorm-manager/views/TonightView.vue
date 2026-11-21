<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'

import { ApiRequestError, api } from '@/shared/api/client'
import type { BuildingTonight, StudentContact, TonightItem } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()

const state = ref<'idle' | 'loading' | 'ready' | 'pending' | 'denied' | 'error'>('idle')
const notice = ref('')
const data = ref<BuildingTonight | null>(null)
const activeBuilding = ref('')
let sequence = 0
function invalidate() { sequence++; data.value = null; contacts.value = {}; contactErrors.value = {}; state.value = 'idle'; notice.value = '' }
watch(activeBuilding, invalidate, { flush: 'sync' })
onBeforeUnmount(invalidate)
const contacts = ref<Record<string, StudentContact>>({})
const contactErrors = ref<Record<string, string>>({})

const buildings = computed(() => session.context?.scope.building_ids ?? [])
// 楼栋名只有值班接口给得出：固定值守读名册、当夜代班读代班表，读不到就退回裸 ID。
const buildingLabels = ref<Record<string, string>>({})
const items = computed<TonightItem[]>(() => data.value?.items ?? [])
const summaryPassed = computed(() => Boolean(data.value?.summary_generated_at))
const changedCount = computed(() => items.value.filter((item) => item.change_flag).length)

const FLAG_LABEL: Record<string, string> = {
  RESCHEDULED: '改期',
  CANCELLED: '撤销',
  ADDED_AFTER_SUMMARY: '汇总后新增',
}

async function loadBuildingLabels() {
  try {
    const [rosterResult, dutyResult] = await Promise.all([api.dutyRoster(), api.duties()])
    const map: Record<string, string> = {}
    for (const row of rosterResult.items) map[row.building_id] = `${row.building_name}（固定值守）`
    for (const row of dutyResult.items) {
      if (row.shift_state !== 'ACTIVE' || !row.building_name) continue
      map[row.building_id] = `${row.building_name}（${map[row.building_id] ? '固定值守 + ' : ''}今晚代班）`
    }
    buildingLabels.value = map
  } catch {
    buildingLabels.value = {}
  }
}

async function load() {
  const requestSequence = ++sequence
  data.value = null
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
    const response = await api.buildingTonight(activeBuilding.value)
    if (requestSequence !== sequence) return
    data.value = response
    state.value = 'ready'
  } catch (cause) {
    if (requestSequence !== sequence) return
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
  void loadBuildingLabels()
})
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>今晚名单</h2>
        <button class="panel__reload" type="button" @click="load" :disabled="state === 'loading'">查询</button>
      </header>

      <nav v-if="buildings.length > 1" class="tonight__tabs">
        <button
          v-for="building in buildings"
          :key="building"
          class="tonight__tab"
          :class="{ 'tonight__tab--active': building === activeBuilding }"
          type="button"
          @click="activeBuilding = building"
        >
          {{ buildingLabels[building] ?? building }}
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
      <p v-else-if="state === 'idle'" class="panel__line">尚未查询，请选择值班楼栋后点击“查询”。</p>
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

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { ApiRequestError, api } from '@/shared/api/client'
import type { ClockState, ListResult, Reservation, ReservationRevision } from '@/shared/api/types'
import StubPanel from '@/shared/components/StubPanel.vue'

const clock = ref<ClockState | null>(null)
const reservation = ref<Reservation | null>(null)
const loading = ref(true)
const busy = ref(false)
const notice = ref('')
const blocked = ref('')

const timeText = ref('')
const reasonText = ref('')
const mode = ref<'idle' | 'create' | 'edit'>('idle')

const history = ref<ListResult<ReservationRevision> | null>(null)
const historyOpen = ref(false)

const STATUS_TEXT: Record<string, string> = {
  ACTIVE: '预约生效中',
  CANCELLED: '已取消',
  FULFILLED: '已返宿',
  CLOSED: '业务夜已结束',
}

const SOURCE_TEXT: Record<string, string> = {
  CREATE: '创建',
  RESCHEDULE: '改期',
  CANCEL: '取消',
  RESTORE: '恢复',
  CLOSE: '系统关闭',
}

const statusText = computed(() => STATUS_TEXT[reservation.value?.status ?? ''] ?? '')

// 门禁时段由服务端给出（night_window），这里只按它列举可选时刻，不写死 00:00–06:00。
const SLOT_STEP_MINUTES = 15

const slots = computed<string[]>(() => {
  const window = clock.value?.night_window
  if (!window || window.length !== 2) return []
  const [start, end] = window
  const day = start.slice(0, 10)
  const limit = end.slice(0, 10) === day ? toMinutes(end) : 24 * 60
  const out: string[] = []
  for (let minute = toMinutes(start); minute < limit; minute += SLOT_STEP_MINUTES) out.push(slotOf(day, minute))
  return out
})

const gateLabel = computed(() => {
  const window = clock.value?.night_window
  if (!window || window.length !== 2) return '等待后端时钟'
  const [start, end] = window
  return `${start.slice(5, 10)} 业务夜 · 返宿时段 ${start.slice(11, 16)}–${end.slice(11, 16)}`
})

const nightTime = computed(() => {
  const planned = reservation.value?.planned_return_at ?? ''
  return planned ? `${planned.slice(5, 10)} ${planned.slice(11, 16)}` : ''
})

const canAct = computed(() => reservation.value?.status === 'ACTIVE')

function toMinutes(moment: string): number {
  return Number(moment.slice(11, 13)) * 60 + Number(moment.slice(14, 16))
}

function slotOf(day: string, minute: number): string {
  return `${day}T${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
}

function firstUpcomingSlot(): string {
  const now = clock.value?.now.slice(0, 16) ?? ''
  const list = slots.value
  return list.find((slot) => slot >= now) ?? list[0] ?? ''
}

function slotForPlanned(planned: string): string {
  const snapped = slotOf(planned.slice(0, 10), Math.floor(toMinutes(planned) / SLOT_STEP_MINUTES) * SLOT_STEP_MINUTES)
  return slots.value.includes(snapped) ? snapped : firstUpcomingSlot()
}

function toPlannedAt(slot: string): string {
  const offset = (clock.value?.now ?? '').slice(-6) || '+08:00'
  return `${slot}:00${offset}`
}

function startCreate() {
  mode.value = 'create'
  notice.value = ''
  reasonText.value = ''
  timeText.value = firstUpcomingSlot()
}

function startEdit() {
  if (!reservation.value) return
  mode.value = 'edit'
  notice.value = ''
  timeText.value = slotForPlanned(reservation.value.planned_return_at)
  reasonText.value = reservation.value.reason
}

function cancelEditing() {
  mode.value = 'idle'
  notice.value = ''
}

async function refresh() {
  const [tonight, state] = await Promise.all([api.tonightReservation(), api.clock()])
  reservation.value = tonight
  clock.value = state
  if (mode.value === 'create' && tonight) mode.value = 'idle'
}

async function run(action: () => Promise<Reservation>, done: string) {
  busy.value = true
  blocked.value = ''
  try {
    reservation.value = await action()
    mode.value = 'idle'
    notice.value = done
    if (historyOpen.value) history.value = await api.reservationRevisions(reservation.value.id)
  } catch (cause) {
    if (cause instanceof ApiRequestError && cause.code === 'VERSION_CONFLICT') {
      await refresh()
      notice.value = ''
      blocked.value = '这一夜的安排已有新版本，已取回最新状态，请重新操作。'
      if (historyOpen.value && reservation.value) {
        history.value = await api.reservationRevisions(reservation.value.id).catch(() => null)
      }
    } else if (cause instanceof ApiRequestError) {
      blocked.value = `${cause.code}：${cause.message}`
    } else {
      blocked.value = '请求未成功，请确认后端仍在运行。'
    }
  } finally {
    busy.value = false
  }
}

function submitCreate() {
  return run(
    () =>
      api.createReservation({
        planned_return_at: toPlannedAt(timeText.value),
        reason: reasonText.value,
      }),
    '预约已提交，自动通过。',
  )
}

function submitEdit() {
  const current = reservation.value
  if (!current) return Promise.resolve()
  return run(
    () =>
      api.updateReservation(current.id, {
        expected_version: current.version,
        planned_return_at: toPlannedAt(timeText.value),
        reason: reasonText.value,
      }),
    '已改期，修改次数不限。',
  )
}

function submitCancel() {
  const current = reservation.value
  if (!current) return Promise.resolve()
  return run(() => api.cancelReservation(current.id, current.version), '预约已取消，可随时恢复。')
}

function submitRestore() {
  const current = reservation.value
  if (!current) return Promise.resolve()
  return run(() => api.restoreReservation(current.id, current.version), '预约已恢复。')
}

async function toggleHistory() {
  historyOpen.value = !historyOpen.value
  if (!historyOpen.value) return
  const current = reservation.value
  if (!current) return
  busy.value = true
  try {
    history.value = await api.reservationRevisions(current.id)
  } catch (cause) {
    blocked.value = cause instanceof ApiRequestError ? `${cause.code}：${cause.message}` : '记录读取失败。'
    history.value = null
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await refresh()
  } catch (cause) {
    blocked.value = cause instanceof ApiRequestError ? `${cause.code}：${cause.message}` : '后端未响应。'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>当日晚归预约</h2>
        <button class="panel__reload" type="button" :disabled="loading" @click="refresh">重新读取</button>
      </header>

      <p class="panel__line">{{ gateLabel }}；时段与是否可改由服务端判定。</p>

      <p v-if="loading" class="panel__line">读取中……</p>

      <div v-else-if="!reservation && mode !== 'create'" class="resv__none">
        <p class="panel__placeholderTitle">今夜还没有预约。</p>
        <p class="panel__placeholderNote">在返宿时段内选一个时刻提交即可，不需要审批。</p>
        <button class="resv__primary" type="button" :disabled="busy" @click="startCreate">
          预约今夜
        </button>
      </div>

      <div v-else-if="!reservation" class="resv__form">
        <label class="resv__field">
          <span class="resv__label">预计返宿时刻</span>
          <select v-model="timeText">
            <option v-for="slot in slots" :key="slot" :value="slot">{{ slot.slice(11, 16) }}</option>
          </select>
        </label>
        <label class="resv__field resv__field--wide">
          <span class="resv__label">原因</span>
          <textarea v-model="reasonText" rows="3" placeholder="一句话说明去向即可。" />
        </label>
        <div class="resv__actions">
          <button class="resv__primary" type="button" :disabled="busy || !slots.length" @click="submitCreate">
            提交预约
          </button>
          <button class="resv__ghost" type="button" :disabled="busy" @click="cancelEditing">收起</button>
        </div>
      </div>

      <div v-else class="resv__card" :class="`resv__card--${reservation.status.toLowerCase()}`">
        <p class="resv__status">
          <span class="resv__dot" aria-hidden="true" />
          {{ statusText }}
          <span class="resv__version">第 {{ reservation.version }} 版</span>
        </p>
        <p v-if="nightTime && reservation.status !== 'CLOSED'" class="resv__time">{{ nightTime }}</p>
        <p v-if="reservation.reason" class="resv__reason">{{ reservation.reason }}</p>

        <div v-if="mode === 'idle'" class="resv__actions">
          <template v-if="canAct">
            <button class="resv__primary" type="button" :disabled="busy" @click="startEdit">改期</button>
            <button class="resv__ghost" type="button" :disabled="busy" @click="submitCancel">取消预约</button>
          </template>
          <button
            v-else-if="reservation.status === 'CANCELLED'"
            class="resv__primary"
            type="button"
            :disabled="busy"
            @click="submitRestore"
          >
            恢复预约
          </button>
          <p v-else class="panel__placeholderNote">本夜记录已关闭，不再接受修改。</p>
        </div>

        <div v-else class="resv__form">
          <label class="resv__field">
            <span class="resv__label">新的返宿时刻</span>
            <select v-model="timeText">
              <option v-for="slot in slots" :key="slot" :value="slot">{{ slot.slice(11, 16) }}</option>
            </select>
          </label>
          <label class="resv__field resv__field--wide">
            <span class="resv__label">原因</span>
            <textarea v-model="reasonText" rows="3" />
          </label>
          <div class="resv__actions">
            <button
              class="resv__primary"
              type="button"
              :disabled="busy || !slots.length"
              @click="submitEdit"
            >
              保存改期
            </button>
            <button class="resv__ghost" type="button" :disabled="busy" @click="cancelEditing">收起</button>
          </div>
        </div>
      </div>

      <p v-if="notice" class="resv__notice">{{ notice }}</p>
      <p v-if="blocked" class="resv__notice resv__notice--bad">{{ blocked }}</p>
    </section>

    <section class="panel">
      <header class="panel__head">
        <h2>核验与出码</h2>
      </header>
      <p class="panel__line">核验窗口由服务端判定，前端只显示结果。</p>
      <StubPanel
        title="现场核验后签发二维码"
        owner="A"
        milestone="M3"
        note="预约时间前后 30 分钟内完成现场核验，核验通过即签发五分钟有效的二维码。"
      />
    </section>

    <section v-if="reservation" class="panel">
      <header class="panel__head">
        <h2>修改记录</h2>
        <button class="panel__reload" type="button" :disabled="busy" @click="toggleHistory">
          {{ historyOpen ? '收起' : '展开' }}
        </button>
      </header>
      <p v-if="!historyOpen" class="panel__line">改期不限次数，每一次都会留痕。</p>
      <ol v-else-if="history" class="resv__log">
        <li v-for="item in history.items" :key="item.id" class="resv__logItem">
          <span class="resv__logSource">{{ SOURCE_TEXT[item.source] ?? item.source }}</span>
          <span class="resv__logTime">{{ item.changed_at.slice(5, 10) }} {{ item.changed_at.slice(11, 16) }}</span>
          <span class="resv__logPlanned">{{ item.planned_return_at.slice(11, 16) }}</span>
          <span v-if="item.reason" class="resv__logReason">{{ item.reason }}</span>
        </li>
      </ol>
      <p v-else class="panel__line">读取中……</p>
    </section>
  </div>
</template>

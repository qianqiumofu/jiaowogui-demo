<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import CampusNightSummary from '@/features/campus/components/CampusNightSummary.vue'
import { api } from '@/shared/api/client'
import type { DutyAssignment, DutyRoster, StaffAccount, StatisticsFilters } from '@/shared/api/types'
import { describeError } from '@/shared/stores/session'

const roster = ref<DutyRoster[]>([])
const duties = ref<DutyAssignment[]>([])
const staff = ref<StaffAccount[]>([])
const parks = ref<StatisticsFilters['parks']>([])
const buildings = ref<StatisticsFilters['buildings']>([])
const loading = ref(true)
const busy = ref<string | null>(null)
const notice = ref<{ text: string; bad: boolean } | null>(null)

// 名册：一栋可以并排夜班与白班两位，写入只动「这一栋这一人」那一行，长期生效。
const fixedBuilding = ref('')
const fixedStaff = ref('')
const shiftFrom = ref('18:00')
const shiftTo = ref('06:00')

// 代班：某一夜多管一栋，窗口是绝对时间，服务端只在那一夜内认它。
const subStaff = ref('')
const subBuilding = ref('')
const start = ref('')
const end = ref('')
const zone = ref('+08:00')

const activeStaff = computed(() => staff.value.filter((item) => item.status === 'ACTIVE'))
const rosterByPark = computed(() =>
  [...roster.value].sort(
    (a, b) =>
      (a.park_name ?? '').localeCompare(b.park_name ?? '') || a.building_name.localeCompare(b.building_name),
  ),
)
const buildingGroups = computed(() =>
  parks.value
    .map((park) => ({ park, items: buildings.value.filter((b) => b.park_org_id === park.org_id) }))
    .filter((group) => group.items.length > 0),
)

function windowText(row: DutyRoster): string {
  return row.shift_start > row.shift_end
    ? `${row.shift_start}–次日 ${row.shift_end}`
    : `${row.shift_start}–${row.shift_end}`
}

function rosterBadge(row: DutyRoster): string {
  if (row.on_duty_now) return '当班中'
  if (row.covers_tonight) return '今晚在班'
  return `自 ${row.valid_from} 生效`
}

function shownTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

async function load() {
  loading.value = true
  try {
    const [rosterResult, dutyResult, accountResult, filters, clock] = await Promise.all([
      api.dutyRoster(),
      api.duties(),
      api.staffAccounts(),
      api.statisticsFilters(),
      api.clock(),
    ])
    roster.value = rosterResult.items
    duties.value = [...dutyResult.items].sort((a, b) => b.shift_start.localeCompare(a.shift_start))
    staff.value = accountResult.items
    parks.value = filters.parks
    buildings.value = filters.buildings
    zone.value = clock.now.slice(-6)
    fixedBuilding.value ||= filters.buildings[0]?.building_id ?? ''
    fixedStaff.value ||= accountResult.items[0]?.id ?? ''
    subStaff.value ||= accountResult.items[0]?.id ?? ''
    subBuilding.value ||= filters.buildings[1]?.building_id ?? filters.buildings[0]?.building_id ?? ''
  } catch (cause) {
    notice.value = { text: describeError(cause), bad: true }
  } finally {
    loading.value = false
  }
}

async function reloadRoster() {
  roster.value = (await api.dutyRoster()).items
  duties.value = (await api.duties()).items
}

// 换人写的是「这栋楼以后每晚归谁」：一次生效到之后每一夜，不需要逐夜点授权。
async function setRoster() {
  if (busy.value || !fixedBuilding.value || !fixedStaff.value) return
  busy.value = 'roster'
  notice.value = null
  try {
    const row = await api.setDutyRoster({
      building_id: fixedBuilding.value,
      staff_user_id: fixedStaff.value,
      shift_start: shiftFrom.value,
      shift_end: shiftTo.value,
    })
    notice.value = {
      text: `${row.building_name} 的固定值班阿姨已登记为 ${row.staff_name}，每晚 ${windowText(row)}，`
        + `自 ${row.valid_from} 起生效；她原来那栋不受影响，那一夜的汇总任务已排上。`,
      bad: false,
    }
    await reloadRoster()
  } catch (cause) {
    notice.value = { text: describeError(cause), bad: true }
  } finally {
    busy.value = null
  }
}

async function revokeRoster(row: DutyRoster) {
  if (busy.value) return
  busy.value = `roster:${row.roster_id}`
  notice.value = null
  try {
    await api.revokeDutyRoster({ building_id: row.building_id, staff_user_id: row.staff_user_id })
    notice.value = {
      text: `${row.building_name} 的 ${row.staff_name} 已卸任：她的可见楼栋当场收回，`
        + '园区建号时绑的那一栋也一并解开，那一夜的晚归单不受影响。',
      bad: false,
    }
    await reloadRoster()
  } catch (cause) {
    notice.value = { text: describeError(cause), bad: true }
  } finally {
    busy.value = null
  }
}

async function grantSubstitute() {
  if (busy.value || !subBuilding.value || !subStaff.value || !start.value || !end.value) return
  busy.value = 'substitute'
  notice.value = null
  try {
    const row = await api.assignDuty({
      staff_user_id: subStaff.value,
      building_id: subBuilding.value,
      shift_start: `${start.value}:00${zone.value}`,
      shift_end: `${end.value}:00${zone.value}`,
    })
    notice.value = {
      text: `${row.building_name ?? subBuilding.value} 的当夜代班已登记，只在服务端判定的区间内生效。`,
      bad: false,
    }
    await reloadRoster()
  } catch (cause) {
    notice.value = { text: describeError(cause), bad: true }
  } finally {
    busy.value = null
  }
}

async function revokeSubstitute(dutyId: string) {
  if (busy.value) return
  busy.value = dutyId
  notice.value = null
  try {
    await api.revokeDuty(dutyId)
    notice.value = { text: '代班已撤销，那一夜的晚归单不受影响。', bad: false }
    await reloadRoster()
  } catch (cause) {
    notice.value = { text: describeError(cause), bad: true }
  } finally {
    busy.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="stack">
    <section class="panel">
      <div class="panel__head">
        <h2>楼栋固定值班名册</h2>
        <button class="panel__reload" type="button" @click="load">刷新</button>
      </div>
      <p class="panel__line">
        每栋楼夜晚的值班阿姨是固定的，登记一次管到之后每一夜；同一栋可以并排夜班与白班两位。
        窗口是「每晚几点到几点」，跨零点由服务端回绕判定，日期一律按业务夜 D＝[D 06:00, D+1 06:00) 算。
      </p>

      <p v-if="notice" class="resv__notice" :class="{ 'resv__notice--bad': notice.bad }">{{ notice.text }}</p>

      <ul v-if="rosterByPark.length" class="staff__list">
        <li v-for="row in rosterByPark" :key="row.roster_id" class="staff__row">
          <div class="staff__main">
            <span class="staff__name">{{ row.building_name }}</span>
            <span class="staff__login">{{ row.park_name ?? '未归属片区' }}</span>
            <span class="staff__tag">{{ rosterBadge(row) }}</span>
          </div>
          <div class="staff__buildings">
            <span class="staff__building">{{ row.staff_name }}</span>
            <span class="staff__building">每晚 {{ windowText(row) }}</span>
            <span class="staff__building">
              {{ row.valid_from }}{{ row.valid_to ? ` – ${row.valid_to}` : ' 起长期' }}
            </span>
          </div>
          <div class="staff__actions">
            <button
              class="resv__ghost"
              type="button"
              :disabled="busy !== null"
              @click="revokeRoster(row)"
            >
              卸任
            </button>
          </div>
        </li>
      </ul>
      <p v-else-if="loading" class="panel__placeholder">读取名册中……</p>
      <p v-else class="panel__placeholder">名册还是空的。给每栋楼定一位固定值班阿姨，之后就不必逐夜授权。</p>

      <form class="resv__form" @submit.prevent="setRoster">
        <label class="resv__field">
          <span class="resv__label">楼栋</span>
          <select v-model="fixedBuilding" required>
            <optgroup v-for="group in buildingGroups" :key="group.park.org_id" :label="group.park.name">
              <option v-for="item in group.items" :key="item.building_id" :value="item.building_id">
                {{ item.name }}
              </option>
            </optgroup>
          </select>
        </label>
        <label class="resv__field">
          <span class="resv__label">固定值班阿姨</span>
          <select v-model="fixedStaff" required>
            <option v-for="item in activeStaff" :key="item.id" :value="item.id">
              {{ item.display_name }}（工号 {{ item.login_name }}）
            </option>
          </select>
        </label>
        <label class="resv__field">
          <span class="resv__label">每晚上岗</span>
          <input v-model="shiftFrom" type="time" required />
        </label>
        <label class="resv__field">
          <span class="resv__label">每晚离岗</span>
          <input v-model="shiftTo" type="time" required />
        </label>
        <div class="resv__actions">
          <button class="resv__primary" type="submit" :disabled="busy !== null">
            {{ busy === 'roster' ? '登记中' : '登记固定值班' }}
          </button>
        </div>
      </form>
    </section>

    <section class="panel">
      <div class="panel__head">
        <h2>当夜代班</h2>
      </div>
      <p class="panel__line">
        代班是在某一夜临时负责指定楼栋，无需先有固定值守楼栋，只在这里登记的区间内生效；固定负责人不靠逐夜授权。
      </p>

      <form class="resv__form" @submit.prevent="grantSubstitute">
        <label class="resv__field">
          <span class="resv__label">代班人</span>
          <select v-model="subStaff" required>
            <option v-for="item in activeStaff" :key="item.id" :value="item.id">
              {{ item.display_name }}（工号 {{ item.login_name }}）
            </option>
          </select>
        </label>
        <label class="resv__field">
          <span class="resv__label">楼栋</span>
          <select v-model="subBuilding" required>
            <optgroup v-for="group in buildingGroups" :key="group.park.org_id" :label="group.park.name">
              <option v-for="item in group.items" :key="item.building_id" :value="item.building_id">
                {{ item.name }}
              </option>
            </optgroup>
          </select>
        </label>
        <label class="resv__field">
          <span class="resv__label">开始（业务时区）</span>
          <input v-model="start" type="datetime-local" required />
        </label>
        <label class="resv__field">
          <span class="resv__label">结束（业务时区）</span>
          <input v-model="end" type="datetime-local" required />
        </label>
        <div class="resv__actions">
          <button class="resv__primary" type="submit" :disabled="busy !== null">
            {{ busy === 'substitute' ? '登记中' : '登记当夜代班' }}
          </button>
        </div>
      </form>

      <details>
        <summary>已登记代班（{{ duties.length }} 条，点击展开）</summary>
        <ul>
          <li v-for="row in duties" :key="row.duty_id">
            {{ row.staff_name ?? row.staff_user_id }} · {{ row.building_name ?? row.building_id }} ·
            {{ row.service_date }} · {{ shownTime(row.shift_start) }} — {{ shownTime(row.shift_end) }}
            · {{ row.shift_state === 'ACTIVE' ? '当班中' : row.shift_state === 'ENDED' ? '已结束' : '未开始' }}
            <button class="resv__ghost" type="button" :disabled="busy !== null" @click="revokeSubstitute(row.duty_id)">
              撤销
            </button>
          </li>
        </ul>
      </details>
    </section>

    <CampusNightSummary />
  </div>
</template>

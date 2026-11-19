<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { ApiRequestError, api } from '@/shared/api/client'
import type { BuildingResident, ClockState, ReturnRecord } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()

const buildings = computed(() => session.context?.scope.building_ids ?? [])
const activeBuilding = ref('')

const query = ref('')
const searchState = ref<'idle' | 'loading' | 'ready' | 'denied' | 'error'>('idle')
const notice = ref('')
const residents = ref<BuildingResident[]>([])

const selected = ref<BuildingResident | null>(null)
const note = ref('按门铃后手动开门')
const submitting = ref(false)
const result = ref<ReturnRecord | null>(null)
const failure = ref('')
let idempotencyKey = ''

const clock = ref<ClockState | null>(null)

async function search() {
  if (!activeBuilding.value) {
    searchState.value = 'denied'
    notice.value = '当前没有生效的值班或代班楼栋。'
    return
  }
  searchState.value = 'loading'
  notice.value = ''
  try {
    const body = await api.buildingResidents(activeBuilding.value, query.value.trim() || undefined)
    residents.value = body.items
    searchState.value = 'ready'
  } catch (cause) {
    residents.value = []
    if (cause instanceof ApiRequestError) {
      if (cause.code.startsWith('FORBIDDEN') || cause.code === 'SCOPE_UNRESOLVED' || cause.code === 'OUT_OF_SCOPE')
        searchState.value = 'denied'
      else searchState.value = 'error'
      notice.value = describeError(cause)
    } else {
      searchState.value = 'error'
      notice.value = String(cause)
    }
  }
}

function pick(resident: BuildingResident) {
  selected.value = resident
  result.value = null
  failure.value = ''
  // 同一次补录用固定幂等键，重复提交只会命中当夜同一条返宿事实。
  idempotencyKey = `manual:${resident.student_id}:${activeBuilding.value}`
}

function clearSelection() {
  selected.value = null
  result.value = null
  failure.value = ''
  idempotencyKey = ''
}

async function submit() {
  if (!selected.value || !activeBuilding.value || submitting.value) return
  submitting.value = true
  failure.value = ''
  result.value = null
  try {
    result.value = await api.manualReturn({
      student_id: selected.value.student_id,
      building_id: activeBuilding.value,
      evidence: { note: note.value.trim() || '按门铃后手动开门' },
      idempotency_key: idempotencyKey || undefined,
    })
    await search()
  } catch (cause) {
    failure.value = describeError(cause)
  } finally {
    submitting.value = false
  }
}

const alreadyReturned = computed(
  () => Boolean(result.value && (result.value.source === 'QR' || result.value.pass_id)),
)

watch(buildings, (list) => {
  if (!list.includes(activeBuilding.value)) activeBuilding.value = list[0] ?? ''
})

onMounted(async () => {
  activeBuilding.value = buildings.value[0] ?? ''
  clock.value = await api.clock().catch(() => null)
  if (activeBuilding.value) search()
})
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>现场补录</h2>
        <span class="manual__hint">{{ clock ? `当前业务时间 ${clock.now}` : '等待后端时钟' }}</span>
      </header>
      <p class="panel__line">
        24:00 后门禁开启，学生按门铃返宿时由宿管在此选取姓名或学号，锁定身份后录入当夜返宿名单；
        补录与扫码共用同一唯一约束，同一夜只产生一条返宿事实。
      </p>

      <nav v-if="buildings.length > 1" class="tonight__tabs">
        <button
          v-for="building in buildings"
          :key="building"
          class="tonight__tab"
          :class="{ 'tonight__tab--active': building === activeBuilding }"
          type="button"
          @click="activeBuilding = building; clearSelection(); search()"
        >
          {{ building }}
        </button>
      </nav>

      <div class="manual__search">
        <input
          v-model="query"
          placeholder="输入姓名或学号检索本楼栋学生"
          @keyup.enter="search"
        />
        <button class="panel__reload" type="button" :disabled="searchState === 'loading'" @click="search">
          检索
        </button>
      </div>

      <p v-if="searchState === 'loading'" class="panel__line">检索中……</p>
      <div v-else-if="searchState === 'denied'" class="panel__placeholder panel__placeholder--denied">
        <p class="panel__placeholderTitle">后端已拒绝此操作。</p>
        <p class="panel__placeholderNote">{{ notice }}</p>
      </div>
      <div v-else-if="searchState === 'error'" class="panel__placeholder panel__placeholder--error">
        <p class="panel__placeholderTitle">检索失败</p>
        <p class="panel__placeholderNote">{{ notice }}</p>
      </div>
      <div v-else-if="searchState === 'ready' && !residents.length" class="panel__placeholder">
        <p class="panel__placeholderTitle">本楼栋名册没有匹配的学生。</p>
        <p class="panel__placeholderNote">换个姓名或学号片段再试。</p>
      </div>

      <ul v-else-if="searchState === 'ready'" class="tonight__list">
        <li v-for="resident in residents" :key="resident.student_id" class="tonight__row">
          <div class="tonight__main">
            <span class="tonight__room">{{ resident.room_no }}</span>
            <span class="tonight__name">{{ resident.display_name }}</span>
            <span class="tonight__meta">{{ resident.school_id }} · {{ resident.college_name }}</span>
          </div>
          <div class="tonight__side">
            <button class="panel__reload" type="button" @click="pick(resident)">选取</button>
          </div>
        </li>
      </ul>
    </section>

    <section v-if="selected" class="panel">
      <header class="panel__head">
        <h2>锁定身份并录入</h2>
        <button class="panel__reload" type="button" :disabled="submitting" @click="clearSelection">
          取消
        </button>
      </header>

      <dl class="records__grid">
        <dt>姓名</dt>
        <dd>{{ selected.display_name }}</dd>
        <dt>学号</dt>
        <dd>{{ selected.school_id }}</dd>
        <dt>楼栋</dt>
        <dd>{{ selected.building_id }}</dd>
        <dt>寝室</dt>
        <dd>{{ selected.room_no }}</dd>
        <dt>学院</dt>
        <dd>{{ selected.college_name }}</dd>
        <dt>年级</dt>
        <dd>{{ selected.grade || '—' }}</dd>
      </dl>

      <label class="manual__field">
        <span>补录备注</span>
        <input v-model="note" placeholder="如：按门铃后手动开门" />
      </label>

      <div class="manual__actions">
        <button class="terminal__submit" type="button" :disabled="submitting" @click="submit">
          {{ submitting ? '录入中……' : '录入当夜返宿名单' }}
        </button>
      </div>

      <div v-if="failure" class="panel__placeholder panel__placeholder--error">
        <p class="panel__placeholderTitle">补录未成功</p>
        <p class="panel__placeholderNote">{{ failure }}</p>
      </div>
      <div v-else-if="result" class="manual__result" :data-tone="alreadyReturned ? 'warn' : 'ok'">
        <p v-if="alreadyReturned" class="panel__line">
          该生当夜已有返宿记录 {{ result.return_id }}（来源 {{ result.source }}，
          时间 {{ result.occurred_at }}），补录未产生第二条。
        </p>
        <p v-else class="panel__line">
          已录入人工补录返宿 {{ result.return_id }}，业务夜 {{ result.service_date }}，
          返宿时间 {{ result.occurred_at }}。可在「今晚名单」「返宿记录」核对。
        </p>
      </div>
    </section>
  </div>
</template>

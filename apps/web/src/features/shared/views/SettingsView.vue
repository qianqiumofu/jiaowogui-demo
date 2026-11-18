<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiRequestError, api } from '@/shared/api/client'
import type { ClockState } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const clock = ref<ClockState | null>(null)
const message = ref('')
const session = useSessionStore()
const router = useRouter()

async function refresh() {
  try {
    clock.value = await api.clock()
    message.value = ''
  } catch (cause) {
    message.value = cause instanceof ApiRequestError ? describeError(cause) : String(cause)
  }
}

async function jump(label: string) {
  if (!clock.value) {
    message.value = '还没取到服务端时间，先刷新。'
    return
  }
  try {
    clock.value = await api.setClock(minutesFor(label, clock.value))
    message.value = ''
  } catch (cause) {
    message.value = describeError(cause)
  }
}

const SERVER_ISO =
  /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::\d{2})?(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})$/

function minutesFor(label: string, state: ClockState): number {
  if (label === '回到现在') return 0
  return label === '推进到23:30' ? until(23, 30, state) : until(0, 10, state)
}

// 目标时刻只由服务端返回的业务时区字符串构造，不用浏览器本地时间，也不管本地钟快钟慢。
function until(hour: number, minute: number, state: ClockState): number {
  const parts = SERVER_ISO.exec(state.now)
  if (!parts) return 0
  const day = parts[1]
  const zone = parts[4]
  const target = Date.parse(`${day}T${pad(hour)}:${pad(minute)}:00${zone}`)
  const next = target > Date.parse(state.now) ? target : target + 86_400_000
  // 服务端「现在」= 真实时间 + 已有偏移，所以新偏移要先把旧偏移补回来。
  return Math.round((next - Date.parse(state.now)) / 60_000) + state.offset_minutes
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

async function logoutNow() {
  try {
    await session.logout()
  } catch (cause) {
    // 会话过期已由 store 视为登出；这里只剩网络不可达等异常，本地令牌已清理，仍跳转登录页。
    session.error = describeError(cause)
  } finally {
    await router.replace({ name: 'login' })
  }
}

onMounted(refresh)
</script>

<template>
  <div class="settings">
    <section class="panel">
      <header class="panel__head">
        <h2>演示时钟</h2>
        <button class="panel__reload" type="button" @click="refresh">刷新</button>
      </header>
      <p class="panel__line">
        {{ clock ? `业务时间 ${clock.now}（偏移 ${clock.offset_minutes} 分钟）` : '后端未连接' }}
      </p>
      <p class="panel__line">推进的是服务端时间，名单与报告的到期判断跟着走。</p>
      <p v-if="message" class="panel__placeholderNote">{{ message }}</p>
      <div class="settings__row">
        <button class="settings__btn" type="button" @click="jump('回到现在')">回到现在</button>
        <button class="settings__btn" type="button" @click="jump('推进到23:30')">推进到 23:30</button>
        <button class="settings__btn" type="button" @click="jump('跨过零点')">跨过零点</button>
      </div>
    </section>
    <section class="panel">
      <header class="panel__head">
        <h2>会话</h2>
      </header>
      <p class="panel__line">{{ session.context?.display_name }} · 到期 {{ session.context?.expires_at }}</p>
      <div class="settings__row">
        <button class="settings__btn" type="button" @click="logoutNow">退出登录</button>
      </div>
    </section>
  </div>
</template>

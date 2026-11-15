<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiRequestError, api } from '@/shared/api/client'
import type { ClockState } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const clock = ref<ClockState | null>(null)
const message = ref('')
const session = useSessionStore()

async function refresh() {
  try {
    clock.value = await api.clock()
    message.value = ''
  } catch (cause) {
    message.value = cause instanceof ApiRequestError ? describeError(cause) : String(cause)
  }
}

async function jump(label: string) {
  const minutes = minutesFor(label)
  try {
    clock.value = await api.setClock(minutes)
    message.value = ''
  } catch (cause) {
    message.value = describeError(cause)
  }
}

function minutesFor(label: string): number {
  if (label === '回到现在') return 0
  if (label === '推进到23:30') return minutesUntil(23, 30)
  return minutesUntil(0, 10)
}

function minutesUntil(hour: number, minute: number): number {
  const now = new Date()
  const target = new Date(now)
  target.setHours(hour, minute, 0, 0)
  if (target <= now) target.setDate(target.getDate() + 1)
  return Math.round((target.getTime() - now.getTime()) / 60000)
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
        <button class="settings__btn" type="button" @click="session.logout()">退出登录</button>
      </div>
    </section>
  </div>
</template>

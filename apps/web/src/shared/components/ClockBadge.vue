<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiRequestError, api } from '@/shared/api/client'
import type { ClockState } from '@/shared/api/types'

const clock = ref<ClockState | null>(null)
const unavailable = ref(false)

const businessTime = ref<string>('')

async function refresh() {
  try {
    clock.value = await api.clock()
    businessTime.value = new Date(clock.value.now).toLocaleString('zh-CN', { hour12: false })
  } catch (cause) {
    unavailable.value = cause instanceof ApiRequestError && cause.code === 'NETWORK_UNAVAILABLE'
  }
}

onMounted(refresh)
</script>

<template>
  <RouterLink to="/app/settings" class="clockbadge" :title="'点击调整演示时钟'">
    <span class="clockbadge__dot" :class="{ 'clockbadge__dot--bad': unavailable }"></span>
    <span v-if="unavailable">后端未连接</span>
    <span v-else>{{ businessTime || '读取中' }}</span>
  </RouterLink>
</template>

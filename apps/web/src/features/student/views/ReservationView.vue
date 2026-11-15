<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '@/shared/api/client'
import type { ClockState } from '@/shared/api/types'
import DataPanel from '@/shared/components/DataPanel.vue'
import StubPanel from '@/shared/components/StubPanel.vue'

const clock = ref<ClockState | null>(null)

onMounted(async () => {
  clock.value = await api.clock().catch(() => null)
})
</script>

<template>
  <div class="stack">
    <DataPanel
      title="当日晚归预约"
      owner="A"
      stage="M2"
      milestone="唯一预约、全部通过、无限改期"
      :loader="api.reservations"
    />
    <section class="panel">
      <header class="panel__head">
        <h2>核验与出码</h2>
      </header>
      <p class="panel__line">
        {{ clock ? `当前业务时间 ${clock.now}` : '等待后端时钟' }}；核验窗口由服务端判定，前端不自行计算。
      </p>
      <StubPanel
        title="现场核验后签发二维码"
        owner="A"
        milestone="M3"
        note="预约时间前后 30 分钟内完成现场核验，核验通过即签发五分钟有效的二维码。"
      />
    </section>
  </div>
</template>

<script setup lang="ts">
import { SOURCE_TEXT } from '@/features/student/labels'
import type { ReservationRevision } from '@/shared/api/types'

defineProps<{ items: ReservationRevision[] }>()
</script>

<template>
  <ol v-if="items.length" class="resv__log">
    <li v-for="item in items" :key="item.id" class="resv__logItem">
      <span class="resv__logSource">{{ SOURCE_TEXT[item.source] ?? item.source }}</span>
      <span class="resv__logTime">{{ item.changed_at.slice(5, 10) }} {{ item.changed_at.slice(11, 16) }}</span>
      <span class="resv__logPlanned">{{ item.planned_return_at.slice(11, 16) }}</span>
      <span v-if="item.reason" class="resv__logReason">{{ item.reason }}</span>
    </li>
  </ol>
  <p v-else class="panel__line">这条预约还没有留痕。</p>
</template>

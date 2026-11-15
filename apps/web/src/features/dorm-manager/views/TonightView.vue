<script setup lang="ts">
import DataPanel from '@/shared/components/DataPanel.vue'
import { api } from '@/shared/api/client'
</script>

<template>
  <div class="stack">
    <DataPanel
      title="今晚名单"
      owner="B"
      stage="M2"
      milestone="23:30 汇总当前预约，之后改期与返宿继续更新"
      :loader="() => api.buildingTonight('bldg_a1')"
    />
  </div>
</template>

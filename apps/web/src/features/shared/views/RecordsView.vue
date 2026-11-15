<script setup lang="ts">
import DataPanel from '@/shared/components/DataPanel.vue'
import { api } from '@/shared/api/client'
</script>

<template>
  <div class="stack">
    <DataPanel
      title="返宿记录"
      owner="B"
      stage="M3"
      milestone="按当前授权范围列出正式记录"
      :loader="api.returnRecords"
    />
  </div>
</template>

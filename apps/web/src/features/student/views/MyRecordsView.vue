<script setup lang="ts">
import DataPanel from '@/shared/components/DataPanel.vue'
import { api } from '@/shared/api/client'
</script>

<template>
  <div class="stack">
    <DataPanel
      title="我的返宿记录"
      owner="B"
      stage="M3"
      milestone="正式返宿记录由扫码回执或人工补录产生"
      :loader="api.returnRecords"
    />
  </div>
</template>

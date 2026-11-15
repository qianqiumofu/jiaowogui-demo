<script setup lang="ts">
import DataPanel from '@/shared/components/DataPanel.vue'
import { api } from '@/shared/api/client'
</script>

<template>
  <div class="stack">
    <DataPanel
      title="风险事件"
      owner="A"
      stage="M4"
      milestone="规则触发后交辅导员与宿管跟进"
      :loader="api.riskEvents"
    />
  </div>
</template>

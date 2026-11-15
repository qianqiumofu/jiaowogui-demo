<script setup lang="ts">
import StubPanel from '@/shared/components/StubPanel.vue'
</script>

<template>
  <div class="stack">
    <StubPanel
      title="全校授权查询"
      owner="B"
      milestone="M4"
      note="按学院、园区、楼栋、年级等条件筛选并统计；人数、晚归夜数与返宿次数分开计算。"
    />
    <StubPanel
      title="受控导出"
      owner="B"
      milestone="M4"
      note="导出字段另设权限，敏感字段与导出范围待学校确认后再开放。"
    />
  </div>
</template>

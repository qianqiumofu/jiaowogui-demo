<script setup lang="ts">
import StubPanel from '@/shared/components/StubPanel.vue'
</script>

<template>
  <div class="stack">
    <StubPanel
      title="负责学生情况"
      owner="B"
      milestone="M1"
      note="目录同步负责关系后，此处按辅导员授权范围列出学生与当晚状态；关系缺失时记配置异常，不向园区投递。"
    />
    <StubPanel
      title="住宿与归属同步"
      owner="B"
      milestone="M1"
      note="住宿、学院、楼栋与负责关系由学校目录适配器映射，学生不可自行更改归属楼栋。"
    />
  </div>
</template>

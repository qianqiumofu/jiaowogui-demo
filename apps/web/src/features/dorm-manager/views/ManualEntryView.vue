<script setup lang="ts">
import StubPanel from '@/shared/components/StubPanel.vue'
</script>

<template>
  <div class="stack">
    <StubPanel
      title="现场补录"
      owner="B"
      milestone="M3"
      note="按门铃等实际返宿由宿管记录，常规路径约三步；补录与扫码共用唯一返宿写入，不产生第二次返宿。"
    />
    <StubPanel
      title="跨楼栋代班"
      owner="B"
      milestone="M1"
      note="代班生效时可见指定多栋，失效后由后端拒绝；权限按有效值班范围校验。"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const token = ref('')
const result = ref('扫码核销能力属于 M3，由 B 交付；当前终端只做占位。')

function scan() {
  result.value = token.value
    ? '设备认证与原子核销尚未实现，未产生返宿记录。'
    : '需要先从学生端取得二维码令牌。'
}
</script>

<template>
  <div class="terminal">
    <header class="terminal__head">
      <h1>门口终端（模拟）</h1>
      <RouterLink to="/">返回登录</RouterLink>
    </header>
    <p class="terminal__mock">模拟设备：不连接真实门禁，不会真实开锁。</p>
    <div class="terminal__scan">
      <input v-model="token" placeholder="粘贴二维码令牌" />
      <button type="button" @click="scan">核销</button>
    </div>
    <p class="terminal__result">{{ result }}</p>
  </div>
</template>

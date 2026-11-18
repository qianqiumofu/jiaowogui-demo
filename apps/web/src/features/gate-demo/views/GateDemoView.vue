<script setup lang="ts">
import { ref } from 'vue'

import { ApiRequestError, api } from '@/shared/api/client'

// 演示设备身份：库里只存 sha256 摘要，明文按 docs/10 的合成约定派生，不是真实门禁密钥。
const DEVICES = [
  { id: 'dev_synth_a1_01', label: 'A1 北门终端（bldg_a1）' },
  { id: 'dev_synth_a2_01', label: 'A2 北门终端（bldg_a2）' },
]

const deviceId = ref(DEVICES[0].id)
const code = ref('')
const lines = ref<string[]>([
  '等待扫码。学生端领码后把令牌粘贴到这里，核销成功才会生成正式返宿记录。',
])
const tone = ref<'idle' | 'ok' | 'warn'>('idle')

const REFUSAL: Record<string, string> = {
  PASS_NOT_FOUND: '二维码无效或不存在，请重新核验领码。',
  GATE_MISMATCH: '二维码与本终端的门禁范围不一致。',
  PASS_REVOKED: '该码已随改期或撤销作废。',
  PASS_EXPIRED: '二维码已超过 300 秒有效期，必须重新领码。',
  NIGHT_ACCESS_ENDED: '夜间通行授权时段已结束（仅 00:00–06:00）。',
  RETURN_EXISTS: '该业务夜已有正式返宿记录，本次不放行。',
  PASS_CONSUMED: '同一码被并发扫码占用，本次不重复放行。',
  DEVICE_UNKNOWN: '终端未登记。',
  DEVICE_UNAUTHORIZED: '终端凭据不匹配。',
}

async function scan() {
  if (!code.value.trim()) {
    tone.value = 'warn'
    lines.value = ['需要先粘贴二维码令牌。']
    return
  }
  tone.value = 'idle'
  try {
    const result = await api.deviceScan(deviceId.value, `dev_synth:${deviceId.value}`, code.value.trim())
    tone.value = 'ok'
    lines.value = [
      result.attempt_status === 'SUCCEEDED' && !result.duplicate
        ? `已放行：返宿记录 ${result.return_id}，返宿时间 ${result.occurred_at ?? '—'}`
        : `重复扫码：本夜已有返宿记录 ${result.return_id ?? '—'}，不产生第二条。`,
      `pass_id：${result.pass_id ?? '—'} · 核销时间 ${result.occurred_at ?? '—'}`,
    ]
  } catch (cause) {
    tone.value = 'warn'
    if (cause instanceof ApiRequestError) {
      lines.value = [
        `${cause.code}：${REFUSAL[cause.code] ?? cause.message}`,
        JSON.stringify(cause.details),
      ]
    } else {
      lines.value = [String(cause)]
    }
  }
}
</script>

<template>
  <div class="terminal">
    <header class="terminal__head">
      <h1>门口终端（模拟）</h1>
      <RouterLink class="terminal__back" to="/">返回登录</RouterLink>
    </header>
    <p class="terminal__mock">模拟设备：不连接真实门禁，不会真实开锁；只记录合成演示数据。</p>

    <label class="terminal__field">
      <span>终端身份</span>
      <select v-model="deviceId">
        <option v-for="device in DEVICES" :key="device.id" :value="device.id">
          {{ device.label }}
        </option>
      </select>
    </label>

    <div class="terminal__scan">
      <input v-model="code" placeholder="粘贴二维码令牌" />
      <button class="terminal__submit" type="button" @click="scan">核销</button>
    </div>

    <div class="terminal__result" :data-tone="tone">
      <p v-for="(line, index) in lines" :key="index">{{ line }}</p>
    </div>
  </div>
</template>

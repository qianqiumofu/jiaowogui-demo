<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '@/shared/api/client'
import type { components } from '@/shared/api/schema'
import { describeError } from '@/shared/stores/session'

type AgentReport = components['schemas']['AgentReport']
const status = ref<components['schemas']['AgentStatus'] | null>(null)
const statusLoading = ref(false)
const statusError = ref('')
const message = ref('')
const running = ref(false)
const error = ref('')
const reports = ref<Array<{ question: string; result: AgentReport }>>([])
const suggestions = ['总结本周我负责学生的实际晚归情况。', '比较本周与上周的正式晚归统计。', '生成本月负责范围的晚归汇总草稿。']

async function loadStatus() {
  statusLoading.value = true
  statusError.value = ''
  try { status.value = await api.reportAgentStatus() }
  catch (cause) { status.value = null; statusError.value = describeError(cause) }
  finally { statusLoading.value = false }
}

async function send() {
  if (running.value || !status.value?.enabled || !message.value.trim()) return
  const question = message.value.trim()
  running.value = true
  error.value = ''
  try {
    const response = await api.runReportAgent(question, reports.value.slice(-4).map(item => item.question))
    reports.value.push({ question, result: response })
    message.value = ''
  } catch (cause) { error.value = describeError(cause) }
  finally { running.value = false }
}

onMounted(loadStatus)
</script>

<template>
  <div class="stack">
    <section class="panel">
      <header class="panel__head">
        <h2>报告助手</h2>
        <button class="panel__reload" :disabled="statusLoading || running" @click="loadStatus">刷新状态</button>
      </header>
      <p class="panel__line">用一句话查询负责范围的实际晚归，生成带数据依据的报告草稿。</p>
      <p v-if="statusLoading" class="panel__line" role="status">检查助手状态……</p>
      <p v-else-if="statusError" class="panel__line" role="alert">{{ statusError }}</p>
      <p v-else class="panel__line" role="status">{{ status?.message }}</p>
      <p v-if="status && !status.enabled" class="panel__line">模型服务接入后即可使用；当前不会向外部模型发送请求。</p>
      <RouterLink to="/app/counselor/reports">打开原有晚归查询</RouterLink>
      <div class="assistant__suggestions">
        <button v-for="example in suggestions" :key="example" class="panel__reload" :disabled="running" @click="message = example">{{ example }}</button>
      </div>
      <form class="assistant__form" @submit.prevent="send">
        <label for="report-question">查询问题</label>
        <textarea id="report-question" v-model="message" rows="3" maxlength="1000" placeholder="例如：总结本周，并和上周比较。" :disabled="running" />
        <div class="stat__actions">
          <button class="terminal__submit" :disabled="running || !status?.enabled || !message.trim()">{{ running ? '正在查询并核对依据……' : '生成报告草稿' }}</button>
          <button class="panel__reload" type="button" :disabled="running || !reports.length" @click="reports = []; error = ''">清空本页对话</button>
        </div>
      </form>
      <p v-if="error" class="panel__line" role="alert">{{ error }}</p>
      <p class="panel__line">仅提供聚合查询。不会修改预约、开锁、处分或发送消息；未确认返宿不代表已证明未归。</p>
    </section>
    <section v-for="entry in reports" :key="entry.result.run_id" class="panel">
      <header class="panel__head"><h2>{{ entry.question }}</h2></header>
      <p class="assistant__answer">{{ entry.result.answer }}</p>
      <details>
        <summary>查看数据依据与执行过程</summary>
        <ul>
          <li v-for="step in entry.result.tool_steps" :key="step.source_id">已读取统计依据 [{{ step.source_id }}]</li>
        </ul>
        <div class="assistant__sources">
          <article v-for="source in entry.result.sources" :key="source.source_id">
            <h3>[{{ source.source_id }}] {{ source.date_from }} 至 {{ source.date_to }}</h3>
            <p>实际晚归 {{ source.totals.people }} 人 · {{ source.totals.nights }} 夜 · 返宿 {{ source.totals.returns }} 次</p>
            <p>扫码 {{ source.totals.qr_returns }} 次 · 人工补录 {{ source.totals.manual_returns }} 次 · 在册 {{ source.totals.enrolled }} 人</p>
          </article>
        </div>
        <p>生成于 {{ entry.result.generated_at }}</p>
      </details>
      <ul><li v-for="note in entry.result.notes" :key="note">{{ note }}</li></ul>
    </section>
  </div>
</template>

<style scoped>
.assistant__form { display: grid; gap: 12px; margin-top: 18px; }
.assistant__form textarea { box-sizing: border-box; width: 100%; resize: vertical; min-height: 110px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; color: inherit; background: var(--bg-raise); font: inherit; }
.assistant__suggestions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
.assistant__answer { white-space: pre-wrap; line-height: 1.8; }
.assistant__sources { display: grid; gap: 12px; }
</style>

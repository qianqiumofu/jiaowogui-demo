<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '@/shared/api/client'
import type { RiskEvent } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()
const rows = ref<RiskEvent[]>([]), status = ref(''), message = ref('')
const notes = ref<Record<string, string>>({}), queried = ref(false), loading = ref(false)
const pending = ref(''), resolveTarget = ref(''), resolveNote = ref('')
const attempts: Record<string, { note: string; key: string }> = {}
const canHandle = computed(() => session.can('risk:ack'))
const labels = { OPEN: '待接手', ACKNOWLEDGED: '跟进中', RESOLVED: '已办结' }
const actionLabels = { ACK: '确认接手', FOLLOW_UP: '记录跟进', RESOLVE: '完成跟进并办结' }
let sequence = 0, alive = true
function invalidate() {
  sequence++; rows.value = []; queried.value = false; loading.value = false; message.value = ''
  resolveTarget.value = ''; notes.value = {}
}
watch(status, invalidate, { flush: 'sync' })
onBeforeUnmount(() => { alive = false; sequence++ })
function shownTime(value: string) { return value.slice(0, 19).replace('T', ' ') }
function factNights(event: RiskEvent) { return Array.isArray(event.facts.nights) ? event.facts.nights.join('、') : '暂无明细' }
async function load() {
  const requestSequence = ++sequence
  loading.value = true; queried.value = false; rows.value = []; message.value = ''; resolveTarget.value = ''
  try {
    const response = await api.riskList(status.value)
    if (!alive || requestSequence !== sequence) return
    rows.value = response.items; queried.value = true
  } catch (cause) {
    if (alive && requestSequence === sequence) message.value = describeError(cause)
  } finally {
    if (alive && requestSequence === sequence) loading.value = false
  }
}
async function act(event: RiskEvent, action: 'ack' | 'follow-up' | 'resolve', reviewedNote?: string) {
  if (!canHandle.value || pending.value) return
  const note = (reviewedNote ?? notes.value[event.id] ?? '').trim()
  if (!note) { message.value = '请先填写本次操作说明。'; return }
  pending.value = event.id; message.value = ''
  try {
    if (action === 'follow-up') {
      if (!attempts[event.id] || attempts[event.id].note !== note) attempts[event.id] = { note, key: crypto.randomUUID() }
      await api.followUpRisk(event.id, note, attempts[event.id].key)
    } else await api.actRisk(event.id, action, note)
    if (!alive) return
    delete attempts[event.id]; notes.value[event.id] = ''; resolveTarget.value = ''
    await load()
    if (alive) message.value = action === 'ack' ? '已确认接手，事件进入跟进中。' : action === 'follow-up' ? '人工跟进记录已保存，事件继续跟进中。' : '已保存办结说明，事件已办结。'
  } catch (cause) { if (alive) message.value = describeError(cause) }
  finally { if (alive) pending.value = '' }
}
function reviewResolve(event: RiskEvent) {
  resolveNote.value = (notes.value[event.id] ?? '').trim()
  if (!resolveNote.value) { message.value = '办结前请写明核实结果与完成情况。'; return }
  resolveTarget.value = event.id
}
</script>

<template><div class="stack risk-workflow">
  <section class="panel">
    <h1>{{ canHandle ? '风险核实与跟进' : '风险主动查询' }}</h1>
    <p>依据正式返宿事实与明确规则进行人工核实。超时或未确认返宿不触发风险。</p>
    <div class="workflow-steps" aria-label="风险处理流程">
      <article><span>01 · 待接手</span><h2>确认接手</h2><p>人工确认收到并准备处理。仅表示有人接手，不代表已核实或已完成。</p></article>
      <article><span>02 · 跟进中</span><h2>记录实际跟进</h2><p>联系学生、核实情况或约定后续安排后，保存操作说明；可追加多次记录。</p></article>
      <article><span>03 · 已办结</span><h2>完成跟进并办结</h2><p>写明核实结果与完成情况后确认办结，保留全部记录。办结不等于处分。</p></article>
    </div>
    <p class="risk-notice"><strong>发邮件 ≠ 跟进。</strong>邮件、站内通知的发送或已读只表示提醒或阅读，不会自动接手、记录跟进或办结。Demo 邮件仅进入模拟收件箱。</p>
    <p v-if="!canHandle" class="risk-access">当前{{ session.roleLabel }}身份仅可查询和查看处理记录。实际操作由负责辅导员、思政教师或当班宿管完成；管理身份不接收风险推送。<RouterLink to="/app/profile">查看我的身份与职责 →</RouterLink></p>
    <p v-else class="risk-access">你可以处理后端授权范围内的事件。先确认接手，再记录跟进或办结；每步都需填写说明并留下操作人和时间。</p>
    <div class="manage-actions"><label>处理状态 <select v-model="status" :disabled="!!pending"><option value="">全部</option><option v-for="(label,key) in labels" :key="key" :value="key">{{ label }}</option></select></label><button :disabled="loading || !!pending" @click="load">查询</button><span v-if="queried">找到 {{ rows.length }} 条事件</span></div>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="loading" role="status">正在查询……</p><p v-else-if="!queried">尚未查询，选择处理状态后点击“查询”。</p><p v-else-if="!rows.length">当前范围和条件下没有风险事件。</p>
  </section>
  <article v-for="event in rows" :key="event.id" class="panel risk-event">
    <header class="risk-event-head"><div><h2>{{ event.display_name ?? event.student_id }}</h2><p>{{ event.school_id ?? event.student_id }} · {{ event.service_date }} 业务夜</p></div><span class="risk-status" :data-status="event.status">{{ labels[event.status] }}</span></header>
    <p>近 {{ event.facts.window_nights }} 夜正式返宿 {{ event.facts.times }} 夜，其中连续 {{ event.facts.consecutive_nights }} 夜。规则版本 {{ event.rule_version }}。</p>
    <details><summary>查看规则依据与事实夜次</summary><p>{{ factNights(event) }}</p><p>规则触发是核实线索，不自动判断学生过错。</p></details>
    <section class="risk-history"><h3>人工处理记录</h3><p v-if="!event.actions?.length">尚无人工处理记录；即使通知已经发送，也仍属于未接手。</p>
      <ol v-else><li v-for="action in event.actions" :key="action.id"><strong>{{ actionLabels[action.action] }}</strong><span>{{ action.actor_display_name ?? action.actor_user_id }} · {{ shownTime(action.created_at) }}</span><p>{{ action.note }}</p></li></ol>
    </section>
    <section class="risk-operations"><h3>处理操作</h3>
      <label v-if="canHandle && event.status !== 'RESOLVED'" class="risk-note">本次操作说明<textarea v-model="notes[event.id]" :disabled="!!pending" maxlength="500" rows="3" placeholder="接手时说明处理安排；跟进时记录沟通与核实情况；办结时写明结果。"></textarea><span>{{ (notes[event.id] ?? '').length }} / 500</span></label>
      <div class="manage-actions">
        <button :disabled="!canHandle || !!pending || event.status !== 'OPEN' || !notes[event.id]?.trim()" @click="act(event,'ack')">1. 确认接手</button>
        <button :disabled="!session.can('risk:follow_up') || !!pending || event.status !== 'ACKNOWLEDGED' || !notes[event.id]?.trim()" @click="act(event,'follow-up')">2. 保存跟进记录</button>
        <button :disabled="!canHandle || !!pending || event.status !== 'ACKNOWLEDGED' || !notes[event.id]?.trim()" @click="reviewResolve(event)">3. 完成跟进并办结</button>
      </div>
      <p v-if="!canHandle">当前为只读身份，操作按钮不可用。</p><p v-else-if="event.status === 'OPEN'">请填写接手说明，再点击“确认接手”；接手后才可记录跟进或办结。</p><p v-else-if="event.status === 'ACKNOWLEDGED'">请记录实际沟通、核实或后续安排。点击“保存跟进记录”会保留跟进中状态。</p><p v-else>此事件已办结，处理历史保留，不能继续追加或覆盖。</p>
      <div v-if="resolveTarget === event.id" class="manage-review"><h3>确认办结</h3><p>确认已完成此事件的人工核实与跟进？以下说明将写入办结记录。</p><p class="review-note">{{ resolveNote }}</p><div class="manage-actions"><button :disabled="!!pending" @click="act(event,'resolve',resolveNote)">确认办结并保存说明</button><button :disabled="!!pending" @click="resolveTarget=''">继续跟进</button></div></div>
      <p v-if="pending === event.id" role="status">正在保存处理记录……</p>
    </section>
  </article>
</div></template>

<style scoped>
.workflow-steps { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 14px; margin: 22px 0; }
.workflow-steps article { border: 1px solid var(--line); border-radius: 12px; padding: 16px; background: var(--bg-raise); }
.workflow-steps span { color: var(--accent); font-size: .85rem; }
.workflow-steps h2 { font-size: 1rem; margin: 10px 0; }
.workflow-steps p,.risk-access { line-height: 1.8; color: var(--ink-dim); }
.risk-notice { border-left: 3px solid var(--warn); padding: 12px 16px; background: var(--bg-raise); line-height: 1.8; }
.risk-access a { display: inline-block; color: var(--accent); margin-left: 8px; }
.risk-event-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.risk-event-head h2 { margin: 0; }
.risk-event-head p { color: var(--ink-dim); }
.risk-status { border: 1px solid var(--line); padding: 7px 12px; border-radius: 999px; white-space: nowrap; }
.risk-status[data-status='OPEN'] { color: var(--warn); }
.risk-status[data-status='ACKNOWLEDGED'] { color: var(--accent); }
.risk-status[data-status='RESOLVED'] { color: var(--ink-dim); }
.risk-history,.risk-operations { margin-top: 20px; border-top: 1px solid var(--line); padding-top: 12px; }
.risk-history ol { padding-left: 24px; }
.risk-history li { padding: 8px 0; }
.risk-history li span { display: block; margin-top: 5px; color: var(--ink-dim); font-size: .85rem; }
.risk-history li p,.review-note { white-space: pre-wrap; overflow-wrap: anywhere; }
.risk-note { display: flex; flex-direction: column; gap: 8px; }
.risk-note span { color: var(--ink-dim); font-size: .8rem; text-align: right; }
summary { cursor: pointer; color: var(--ink-dim); }
@media(max-width: 800px) { .workflow-steps { grid-template-columns: 1fr; } }
</style>

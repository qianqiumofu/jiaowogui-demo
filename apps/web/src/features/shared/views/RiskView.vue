<script setup lang="ts">
import { onMounted,ref } from 'vue'
import { api } from '@/shared/api/client'
import type { RiskEvent } from '@/shared/api/types'
import { describeError,useSessionStore } from '@/shared/stores/session'
const session=useSessionStore(),rows=ref<RiskEvent[]>([]),status=ref(''),message=ref(''),notes=ref<Record<string,string>>({})
const labels:Record<string,string>={OPEN:'待跟进',ACKNOWLEDGED:'已确认',RESOLVED:'已解决'}
async function load(){try{rows.value=(await api.riskList(status.value)).items}catch(e){message.value=describeError(e)}}
async function act(id:string,action:'ack'|'resolve'){try{await api.actRisk(id,action,notes.value[id]??'');message.value='跟进记录已保存。';await load()}catch(e){message.value=describeError(e)}}
onMounted(load)
</script>
<template><section class="panel"><h2>{{ session.can('risk:ack')?'风险核实与跟进':'风险主动查询' }}</h2><p>仅依据明确规则与正式返宿事实；超时或未确认返宿不触发。园区和学院管理身份只读查询，不因管理身份接收风险推送。</p><label>状态<select v-model="status" @change="load"><option value="">全部</option><option v-for="(label,key) in labels" :key="key" :value="key">{{ label }}</option></select></label><button @click="load">刷新</button><p v-if="message" role="status">{{ message }}</p><p v-if="!rows.length">当前范围没有风险事件。</p><article v-for="r in rows" :key="r.id" class="risk-card"><h3>{{ r.student_id }} · {{ labels[r.status] }}</h3><p>{{ r.service_date }} 业务夜 · 规则 {{ r.rule_version }}</p><p>近 {{ r.facts.window_nights }} 夜实际返宿 {{ r.facts.times }} 夜，连续 {{ r.facts.consecutive_nights }} 夜。</p><p>事实夜次：{{ r.facts.nights }}</p><ol v-if="r.actions?.length"><li v-for="a in r.actions" :key="a.id">{{ a.created_at }} · {{ a.action === 'ACK' ? '确认接手' : '记录解决' }} · {{ a.note }}</li></ol><template v-if="session.can('risk:ack')&&r.status!=='RESOLVED'"><label>核实说明<textarea v-model="notes[r.id]" maxlength="500" rows="2"></textarea></label><button :disabled="!notes[r.id]?.trim()||r.status==='ACKNOWLEDGED'" @click="act(r.id,'ack')">确认接手</button><button :disabled="!notes[r.id]?.trim()" @click="act(r.id,'resolve')">记录解决</button></template></article></section></template>

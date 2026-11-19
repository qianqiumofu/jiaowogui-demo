<script setup lang="ts">
import { onMounted,ref } from 'vue'
import { api } from '@/shared/api/client'
import type { RiskPolicy } from '@/shared/api/types'
import { describeError } from '@/shared/stores/session'
const policy=ref<RiskPolicy|null>(null), message=ref('')
onMounted(async()=>{try{policy.value=await api.riskPolicy()}catch(e){message.value=describeError(e)}})
async function save(){if(!policy.value)return;try{policy.value=await api.saveRiskPolicy(policy.value);message.value='新规则版本已发布，旧版本和变更人保留审计。'}catch(e){message.value=describeError(e)}}
</script>
<template><section class="panel"><h2>版本化风险规则</h2><p>演示规则依据正式返宿的次数与连续性。超时及未确认返宿不触发提醒。园区只管理规则和主动查询，不接收风险推送。</p><p v-if="message" role="status">{{ message }}</p><form v-if="policy" class="manage-grid" @submit.prevent="save"><label>新版本号<input v-model="policy.version" required maxlength="64"></label><label>统计窗口（夜）<input v-model.number="policy.window_nights" type="number" min="1" max="365"></label><label>次数阈值<input v-model.number="policy.times_threshold" type="number" min="1" max="365"></label><label>连续夜数阈值<input v-model.number="policy.consecutive_threshold" type="number" min="1" max="365"></label><button type="submit">发布新版本</button></form></section></template>

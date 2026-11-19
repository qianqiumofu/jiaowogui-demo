<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/shared/api/client'
import { describeError,useSessionStore } from '@/shared/stores/session'
const props=defineProps<{id:string}>(),session=useSessionStore()
const open=ref(false),evidence=ref<Record<string,unknown>[]>([]),corrections=ref<Record<string,unknown>[]>([]),message=ref(''),note=ref('')
const correctedAt=ref('')
async function load(){open.value=true;try{const [e,c]=await Promise.all([api.returnEvidence(props.id),api.corrections(props.id)]);evidence.value=e.items;corrections.value=c.items}catch(e){message.value=describeError(e)}}
async function save(){try{await api.correctReturn(props.id,{note:note.value,...(correctedAt.value?{occurred_at:`${correctedAt.value}:00+08:00`}:{})});note.value='';correctedAt.value='';await load();message.value='更正证据已追加，原始记录保留。'}catch(e){message.value=describeError(e)}}
</script>
<template><div><button type="button" @click="open?open=false:load()">{{ open?'收起证据':'证据与纠错历史' }}</button><div v-if="open"><p v-if="message" role="status">{{ message }}</p><p v-for="e in evidence" :key="String(e.id)">{{ e.created_at }} · {{ e.kind }} · {{ e.payload }}</p><p v-for="c in corrections" :key="String(c.id)">{{ c.created_at }} · 更正：{{ c.note }} {{ c.occurred_at??'' }}</p><form v-if="session.can('return:correct')" @submit.prevent="save"><label>追加更正说明<textarea v-model="note" maxlength="500" required></textarea></label><label>核实后的发生时间（上海时间，可留空）<input v-model="correctedAt" type="datetime-local"></label><button type="submit">保留原记录并追加更正</button></form></div></div></template>

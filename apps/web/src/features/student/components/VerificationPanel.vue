<script setup lang="ts">
import { onUnmounted,ref,watch } from 'vue'
import { api } from '@/shared/api/client'
import type { Reservation,VerificationResult } from '@/shared/api/types'
import { describeError } from '@/shared/stores/session'
const props=defineProps<{reservation:Reservation|null}>()
const issued=ref<VerificationResult|null>(null),face=ref(true),presence=ref(true),busy=ref(false),message=ref(''),state=ref('')
let timer:ReturnType<typeof setInterval>|undefined
function clear(){issued.value=null;state.value='';if(timer)clearInterval(timer)}
watch(()=>props.reservation?.version,clear)
const labels:Record<string,string>={ALLOWED:'服务端判定：可用于本夜通行',NIGHT_NOT_STARTED:'夜间门禁尚未开启',CODE_EXPIRED:'二维码已过期，请重新核验',NIGHT_ACCESS_ENDED:'本夜夜间授权已结束',CONSUMED:'二维码已占用，请查看返宿记录／回执',REVOKED:'二维码已撤销，需重新核验'}
async function refresh(){if(!issued.value)return;try{const body=await fetchState(issued.value.verification_id);state.value=String(body.pass_state??body.status)}catch(e){message.value=describeError(e)}}
async function fetchState(id:string){return api.verificationState(id)}
async function verify(){if(!props.reservation)return;busy.value=true;message.value='';clear();try{issued.value=await api.verify({reservation_id:props.reservation.id,expected_version:props.reservation.version,face_result:face.value,presence_result:presence.value});await refresh();timer=setInterval(()=>void refresh(),5000)}catch(e){message.value=describeError(e)}finally{busy.value=false}}
onUnmounted(clear)
</script>
<template><div class="verify-panel"><p>模拟人脸与现场核验，不采集真实照片、定位或生物信息。</p><label><input v-model="face" type="checkbox">模拟人脸通过</label><label><input v-model="presence" type="checkbox">模拟现场通过</label><button :disabled="busy||!reservation||reservation.status!=='ACTIVE'||reservation.verification.state!=='OPEN'" @click="verify">{{ busy?'核验中…':'现场核验并生成二维码' }}</button><p v-if="message" role="alert">{{ message }}</p><template v-if="issued"><p>{{ labels[state]??state }}</p><div v-if="['ALLOWED','NIGHT_NOT_STARTED'].includes(state)" class="verify-qr" v-html="issued.pass.qr_svg"></div><p>模拟凭证 · 服务端到期时刻 {{ issued.pass.expires_at }}</p><details v-if="['ALLOWED','NIGHT_NOT_STARTED'].includes(state)"><summary>模拟终端用令牌</summary><code class="verify-token">{{ issued.pass.token }}</code><RouterLink to="/terminal" target="_blank">打开模拟终端</RouterLink></details><button @click="refresh">读取服务端状态</button><p>过期后必须重新核验；刷新页面不会延长有效期。通行后请随手关门。</p></template></div></template>

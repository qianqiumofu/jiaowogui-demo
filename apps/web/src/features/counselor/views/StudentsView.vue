<script setup lang="ts">
import { computed,onMounted,ref } from 'vue'
import { api } from '@/shared/api/client'
import type { StudentDirectoryItem } from '@/shared/api/types'
import { describeError,useSessionStore } from '@/shared/stores/session'
const session=useSessionStore(), rows=ref<StudentDirectoryItem[]>([]), all=ref<StudentDirectoryItem[]>([]),message=ref('')
const filters=ref({college_org_id:'',major:'',grade:'',class_name:'',q:''})
const title=computed(()=>session.activeRole==='COLLEGE_ADMIN'?'本学院全体学生':'负责学生')
const colleges=computed(()=>Array.from(new Map(all.value.map(r=>[r.college_org_id,r.college_name])).entries()))
const options=(key:'major'|'grade'|'class_name')=>Array.from(new Set(all.value.map(r=>r[key]))).sort()
async function load(){try{rows.value=(await api.directoryStudents(Object.fromEntries(Object.entries(filters.value).filter(([,v])=>v)))).items}catch(e){message.value=describeError(e)}}
onMounted(async()=>{await load();all.value=rows.value})
</script>
<template><section class="panel"><h2>{{ title }}</h2><p>结果由后端按获授学院或负责学生关系收窄；没有晚归预约的学生也在名册内。</p><p v-if="message" role="alert">{{ message }}</p><form class="manage-grid" @submit.prevent="load"><label>学院<select v-model="filters.college_org_id"><option value="">全部授权学院</option><option v-for="[id,name] in colleges" :key="id" :value="id">{{ name }}</option></select></label><label v-for="key in (['major','grade','class_name'] as const)" :key="key">{{ {major:'专业',grade:'年级',class_name:'班级'}[key] }}<select v-model="filters[key]"><option value="">全部</option><option v-for="v in options(key)" :key="v" :value="v">{{ v }}</option></select></label><label>姓名／学号<input v-model="filters.q"></label><button type="submit">筛选</button></form><p>共 {{ rows.length }} 人</p><div class="manage-table"><table><thead><tr><th>学号</th><th>姓名</th><th>学院／专业</th><th>年级／班级</th><th>楼栋</th></tr></thead><tbody><tr v-for="r in rows" :key="r.student_id"><td>{{ r.school_id }}</td><td>{{ r.display_name }}</td><td>{{ r.college_name }} · {{ r.major }}</td><td>{{ r.grade }} · {{ r.class_name }}</td><td>{{ r.building_id??'未同步' }}</td></tr></tbody></table></div></section></template>

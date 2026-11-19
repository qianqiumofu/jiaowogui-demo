<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/shared/api/client'
import type { UserProfile } from '@/shared/api/types'
import { describeError, ROLE_LABEL, useSessionStore } from '@/shared/stores/session'
const session = useSessionStore()
const labels: Record<string,string> = {building_id:'楼栋编号',room_no:'房间',campus_org_id:'园区编号',park_name:'园区',school_id:'学号',display_name:'姓名',college_org_id:'学院编号',college_name:'学院',grade:'年级',gender:'性别',phone:'联系方式'}
const profile = ref<UserProfile | null>(null)
const home = ref<Record<string, unknown> | null>(null)
const error = ref('')
onMounted(async () => { try { profile.value = await api.profile(); if (session.activeRole === 'STUDENT') home.value = await api.residence() } catch(e) { error.value = describeError(e) } })
</script>
<template><section class="panel"><h2>学校身份与工作职责</h2><p v-if="error" role="alert">{{ error }}</p><template v-if="profile"><p>{{ profile.display_name }} · {{ profile.position_title }}</p><p>基础身份：{{ profile.identity_types.map(x => ({STUDENT:'学生',TEACHER:'教师',EMPLOYEE:'雇佣人员'}[x] ?? x)).join('、') }}</p><p>获授职责：{{ profile.roles.map(x => ROLE_LABEL[x]).join('、') }}</p><p>职责和负责范围由管理部门授予；任课教师不会自动获得辅导员权限。</p><dl v-if="home"><template v-for="(value,key) in home" :key="key"><dt>{{ labels[key] ?? key }}</dt><dd>{{ value }}</dd></template></dl></template></section></template>

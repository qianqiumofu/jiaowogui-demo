<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/shared/api/client'
import { describeError, useSessionStore } from '@/shared/stores/session'
import type { StudentDirectoryItem } from '@/shared/api/types'
const session = useSessionStore()
const students = ref<StudentDirectoryItem[]>([]), error = ref(''), loaded = ref(false)
const school = computed(() => session.activeRole === 'AUTH_ADMIN')
const campus = computed(() => session.activeRole === 'CAMPUS')
const title = computed(() => school.value ? '校级管理工作台' : campus.value ? '园区运营工作台' : '学院管理工作台')
const collegeCount = computed(() => new Set(students.value.map(s => s.college_org_id)).size)
const classCount = computed(() => new Set(students.value.map(s => `${s.college_org_id}/${s.class_name}`)).size)
const buildingCount = computed(() => new Set(students.value.map(s => s.building_id).filter(Boolean)).size)
const steps = computed(() => school.value ? [
  { title: '1. 指定学院负责人', text: '选择教师，授予学院管理职责并明确管理学院。', to: '/app/management/permissions', label: '查看与任命学院负责人' },
  { title: '2. 查看全校晚归情况', text: '查看日、周、月人数统计；按学院、年级、宿舍区与楼栋主动查询晚归和预约名单。', to: '/app/management/statistics', label: '查看晚归情况' },
] : campus.value ? [
  { title: '1. 查看全校晚归情况', text: '按学院、楼栋和业务夜比较实际返宿事实，查看聚合统计并导出。', to: '/app/campus/query', label: '打开统计与查询' },
  { title: '2. 管理宿管与排班', text: '先注册宿管工作账号、绑定固定楼栋，再安排日常值班或临时代班。', to: '/app/campus/staff-accounts', label: '管理宿管账号' },
  { title: '3. 安排楼栋值班', text: '为已注册宿管指定楼栋和起止时刻，代班权限由服务端按生效时间计算。', to: '/app/campus/duties', label: '安排值班与代班' },
  { title: '4. 维护风险规则', text: '主动查询规则命中情况；跟进通知只投递负责教师与当班宿管。', to: '/app/campus/risk-policy', label: '查看规则版本' },
] : [
  { title: '1. 查看学院学生', text: '按专业、年级和班级查找学生，核对学院名册与住宿归属。', to: '/app/counselor/students', label: '查看学院名册' },
  { title: '2. 分配负责教师', text: '在本学院内选择辅导员或思政教师，按班级批量分配学生。', to: '/app/management/permissions', label: '分配教师与学生' },
  { title: '3. 查看日报与记录', text: '从学院日报、周报和正式返宿记录了解情况，再主动查询风险跟进进度。', to: '/app/counselor/reports', label: '查看学院报告' },
])
onMounted(async () => { try { students.value = (await api.directoryStudents()).items; loaded.value = true } catch(e) { error.value = describeError(e) } })
</script>
<template><div class="stack">
  <section class="panel leadership-intro"><p class="leadership-kicker">{{ session.roleLabel }} · 当前授权范围</p><h1>{{ title }}</h1>
    <p>{{ school ? '从学院负责人开始，逐层落实教师职责与负责范围。' : campus ? '先看全校情况，再处理楼栋人员、值班与规则配置。' : '先了解本院情况，再分配负责教师、查看报告与跟进进度。' }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="loaded" class="leadership-metrics"><div><strong>{{ students.length }}</strong><span>授权范围学生</span></div><div><strong>{{ collegeCount }}</strong><span>学院</span></div><div><strong>{{ classCount }}</strong><span>班级</span></div><div><strong>{{ buildingCount }}</strong><span>住宿楼栋</span></div></div>
  </section>
  <section class="leadership-cards" aria-label="管理工作流程"><article v-for="step in steps" :key="step.title" class="panel"><h2>{{ step.title }}</h2><p>{{ step.text }}</p><RouterLink :to="step.to">{{ step.label }} →</RouterLink></article></section>
  <section class="panel"><h2>职责分工</h2><p>校级领导任免学院负责人并查看全校晚归情况；学院负责人决定本院思政、辅导员及负责班级与学生；园区负责全校查询、宿管账号和值班。辅导员与专职思政教师只查看明确分配的学生。</p><p>未确认返宿仅是查询状态，不代表已证明未归，不产生超时提醒。预约均自动通过。</p></section>
</div></template>

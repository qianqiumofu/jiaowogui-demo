<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/shared/api/client'
import type { ManagedUser, RoleGrant, StudentDirectoryItem, Role } from '@/shared/api/types'
import { describeError, ROLE_LABEL, useSessionStore } from '@/shared/stores/session'
const session = useSessionStore()
const users = ref<ManagedUser[]>([]), grants = ref<RoleGrant[]>([]), allStudents = ref<StudentDirectoryItem[]>([])
const audit = ref<Record<string, unknown>[]>([]), message = ref(''), busy = ref(false), reviewing = ref(false)
const selectedUser = ref(''), role = ref<Role>(session.activeRole==='AUTH_ADMIN'?'COLLEGE_ADMIN':'COUNSELOR'), picked = ref<string[]>([]), colleges = ref<string[]>([])
const teacherQuery = ref(''), teacherCollege = ref(''), recordQuery = ref('')
const filters = ref({ college_org_id: '', major: '', grade: '', class_name: '', q: '' })
const page = ref(1), pageSize = 50
const isSchool = computed(() => session.activeRole === 'AUTH_ADMIN')
const roles = computed<Role[]>(() => isSchool.value ? ['COLLEGE_ADMIN', 'COUNSELOR', 'IDEOLOGY', 'CAMPUS'] : ['COUNSELOR', 'IDEOLOGY'])
const teachers = computed(() => users.value.filter(u => u.identity_types.includes('TEACHER')))
const visibleTeachers = computed(() => teachers.value.filter(u => (!teacherCollege.value || u.college_org_id === teacherCollege.value) && `${u.display_name} ${u.school_id}`.toLowerCase().includes(teacherQuery.value.toLowerCase())))
const selectedTeacher = computed(() => teachers.value.find(u => u.user_id === selectedUser.value))
const current = computed(() => grants.value.find(g => g.user_id === selectedUser.value && g.role === role.value && g.active))
const collegeOptions = computed(() => Array.from(new Map(allStudents.value.map(s => [s.college_org_id, s.college_name])).entries()))
const studentRole = computed(() => role.value === 'COUNSELOR' || role.value === 'IDEOLOGY')
const filtered = computed(() => allStudents.value.filter(s => Object.entries(filters.value).every(([key, value]) => !value || (key === 'q' ? `${s.display_name} ${s.school_id}`.toLowerCase().includes(value.toLowerCase()) : s[key as keyof StudentDirectoryItem] === value))))
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const option = (key: 'major' | 'grade' | 'class_name') => Array.from(new Set(allStudents.value.filter(s => !filters.value.college_org_id || s.college_org_id === filters.value.college_org_id).map(s => s[key]))).sort()
const added = computed(() => picked.value.filter(id => !current.value?.student_ids.includes(id)).length)
const removed = computed(() => (current.value?.student_ids ?? []).filter(id => !picked.value.includes(id)).length)
const records = computed(() => grants.value.filter(g => roles.value.includes(g.role) && `${users.value.find(u => u.user_id === g.user_id)?.display_name ?? ''} ${ROLE_LABEL[g.role]}`.includes(recordQuery.value)))
function hydrate() { picked.value = [...(current.value?.student_ids ?? [])]; colleges.value = [...(current.value?.college_org_ids ?? [])]; reviewing.value = false }
watch([selectedUser, role], hydrate)
watch(filters, () => { page.value = 1; reviewing.value = false }, { deep: true })
watch([picked, colleges], () => { reviewing.value = false }, { deep: true })
function selectFiltered() { picked.value = [...new Set([...picked.value, ...filtered.value.map(s => s.student_id)])] }
function removeFiltered() { const ids = new Set(filtered.value.map(s => s.student_id)); picked.value = picked.value.filter(id => !ids.has(id)) }
async function load() {
  busy.value = true
  try {
    const [u, g, s, a] = await Promise.all([api.managedUsers({identity_type:'TEACHER'}), api.grants(), api.directoryStudents(), api.audit()])
    users.value = u.items; grants.value = g.items; allStudents.value = s.items; audit.value = a.items
    hydrate()
  } catch(e) { message.value = describeError(e) } finally { busy.value = false }
}
async function save() {
  busy.value = true
  try { await api.grant({ user_id: selectedUser.value, role: role.value, student_ids: studentRole.value ? picked.value : [], college_org_ids: role.value === 'COLLEGE_ADMIN' ? colleges.value : [] }); message.value = '职责及范围已保存，目标人员重新登录后生效。'; await load() }
  catch(e) { message.value = describeError(e) } finally { busy.value = false; reviewing.value = false }
}
const revokeTarget = ref<RoleGrant | null>(null)
async function revoke() {
  if (!revokeTarget.value) return
  busy.value = true
  try { await api.revokeGrant(revokeTarget.value.id); message.value = '职责已撤回。'; revokeTarget.value = null; await load() }
  catch(e) { message.value = describeError(e) } finally { busy.value = false }
}
onMounted(load)
</script>
<template><div class="stack permissions-view">
  <section class="panel"><h1>{{ isSchool ? '全校职责与负责关系' : '本学院教师与负责关系' }}</h1><p>{{ isSchool ? '先指定各学院负责人，再由学院分配辅导员与思政教师。' : '为本院教师配置工作职责，并按班级分配负责学生。' }}</p><p v-if="message" role="status">{{ message }}</p><p v-if="busy">正在处理……</p></section>
  <section class="panel"><h2>1. 选择教师与工作职责</h2>
    <div class="manage-grid"><label>教师所属学院<select v-model="teacherCollege"><option value="">全部授权学院</option><option v-for="[id,name] in collegeOptions" :key="id" :value="id">{{ name }}</option></select></label><label>查找教师<input v-model="teacherQuery" placeholder="姓名或工号"></label><label>教师<select v-model="selectedUser" :disabled="busy"><option value="">请选择</option><option v-for="u in visibleTeachers" :key="u.user_id" :value="u.user_id">{{ u.display_name }} · {{ u.school_id }}</option></select></label><label>工作职责<select v-model="role" :disabled="busy"><option v-for="r in roles" :key="r" :value="r">{{ ROLE_LABEL[r] }}</option></select></label></div>
    <p v-if="selectedTeacher">当前选择：{{ selectedTeacher.display_name }} · {{ selectedTeacher.position_title }}；{{ current ? '正在编辑现有职责' : '将新增此职责' }}。</p>
  </section>
  <section class="panel"><h2>2. 明确管理范围</h2>
    <fieldset v-if="role==='COLLEGE_ADMIN'"><legend>获授管理学院（可多选）</legend><label v-for="[id,name] in collegeOptions" :key="id"><input v-model="colleges" type="checkbox" :value="id">{{ name }}　</label></fieldset>
    <p v-else-if="role==='CAMPUS'">园区职责提供全校查询、宿管账号和值班管理。学生风险通知仍只投递负责教师与当班宿管。</p>
    <template v-else-if="studentRole"><div class="manage-grid"><label>学院<select v-model="filters.college_org_id"><option value="">全部授权学院</option><option v-for="[id,name] in collegeOptions" :key="id" :value="id">{{ name }}</option></select></label><label v-for="key in (['major','grade','class_name'] as const)" :key="key">{{ {major:'专业',grade:'年级',class_name:'班级'}[key] }}<select v-model="filters[key]"><option value="">全部</option><option v-for="v in option(key)" :key="v" :value="v">{{ v }}</option></select></label><label>查找学生<input v-model="filters.q" placeholder="姓名或学号"></label></div>
      <div class="manage-actions"><strong>已选 {{ picked.length }} 人</strong><span>筛选结果 {{ filtered.length }} 人</span><button :disabled="busy || !filtered.length" @click="selectFiltered">加入全部筛选结果</button><button :disabled="busy || !filtered.length" @click="removeFiltered">移除筛选结果</button><button :disabled="busy" @click="hydrate">恢复已保存范围</button></div>
      <p>筛选只改变显示；“加入全部筛选结果”覆盖全部 {{ pages }} 页。其他筛选下已选的学生会保留。</p>
      <div class="manage-students"><label v-for="s in paged" :key="s.student_id"><input v-model="picked" type="checkbox" :value="s.student_id" :disabled="busy">{{ s.school_id }} {{ s.display_name }} · {{ s.college_name }} · {{ s.class_name }}</label><p v-if="!filtered.length">当前条件下没有学生。</p></div>
      <div class="manage-actions"><button :disabled="page<=1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page>=pages" @click="page++">下一页</button></div>
    </template>
  </section>
  <section class="panel"><h2>3. 核对并保存</h2><p>保存会替换该教师此项职责的完整范围；其他职责保持各自授权。目标人员的现有会话将失效。</p>
    <button v-if="!reviewing" :disabled="busy || !selectedTeacher || (role==='COLLEGE_ADMIN' && !colleges.length)" @click="reviewing=true">预览本次变更</button>
    <div v-else class="manage-review"><p><strong>{{ selectedTeacher?.display_name }} · {{ ROLE_LABEL[role] }}</strong></p><p v-if="studentRole">负责 {{ picked.length }} 名学生，较当前新增 {{ added }} 人、移除 {{ removed }} 人。</p><p v-else-if="role==='COLLEGE_ADMIN'">管理学院：{{ colleges.map(id=>collegeOptions.find(c=>c[0]===id)?.[1]).join('、') }}</p><p v-else>管理范围：园区全校授权。</p><div class="manage-actions"><button :disabled="busy" @click="save">确认保存职责与范围</button><button :disabled="busy" @click="reviewing=false">继续修改</button></div></div>
  </section>
  <section class="panel"><h2>现有职责记录</h2><label>查找教师或职责 <input v-model="recordQuery" placeholder="例如：数学学院"></label><div class="manage-table"><table><thead><tr><th>教师</th><th>职责</th><th>范围</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="g in records" :key="g.id"><td>{{ users.find(u=>u.user_id===g.user_id)?.display_name ?? g.user_id }}</td><td>{{ ROLE_LABEL[g.role] }}</td><td>{{ g.role==='COLLEGE_ADMIN' ? g.college_org_ids.map(id=>collegeOptions.find(c=>c[0]===id)?.[1]??id).join('、') : ['COUNSELOR','IDEOLOGY'].includes(g.role) ? `${g.student_ids.length} 名学生` : '按职责授权' }}</td><td>{{ g.active?'有效':'已撤回' }}</td><td><button v-if="roles.includes(g.role)" :disabled="busy" @click="selectedUser=g.user_id;role=g.role">编辑</button> <button v-if="g.active&&roles.includes(g.role)" :disabled="busy" @click="revokeTarget=g">撤回</button></td></tr></tbody></table></div>
    <div v-if="revokeTarget" class="manage-review"><p>确认撤回 {{ users.find(u=>u.user_id===revokeTarget?.user_id)?.display_name }} 的{{ ROLE_LABEL[revokeTarget.role] }}职责？该职责的负责关系将同步撤回。</p><div class="manage-actions"><button :disabled="busy" @click="revoke">确认撤回</button><button @click="revokeTarget=null">取消</button></div></div>
  </section>
  <details class="panel"><summary>查看权限变更审计（{{ audit.length }} 条）</summary><p v-for="a in audit" :key="String(a.id)">{{ a.created_at }} · {{ a.action }} · {{ a.target }}</p><p v-if="!audit.length">暂无权限变更记录。</p></details>
</div></template>

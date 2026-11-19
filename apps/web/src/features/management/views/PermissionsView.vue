<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '@/shared/api/client'
import type { ManagedUser, RoleGrant, StudentDirectoryItem, Role } from '@/shared/api/types'
import { describeError, ROLE_LABEL, useSessionStore } from '@/shared/stores/session'
const session = useSessionStore()
const users = ref<ManagedUser[]>([]), grants = ref<RoleGrant[]>([]), allStudents = ref<StudentDirectoryItem[]>([])
const audit = ref<Record<string, unknown>[]>([]), message = ref(''), busy = ref(false), reviewing = ref(false)
const selectedUser = ref(''), role = ref<Role>(session.activeRole==='AUTH_ADMIN'?'COLLEGE_ADMIN':'COUNSELOR'), picked = ref<string[]>([]), colleges = ref<string[]>([])
const teacherQuery = ref(''), teacherCollege = ref(''), recordQuery = ref('')
const collegeQuery = ref(''), recordStatus = ref('ACTIVE'), recordRole = ref(''), recordTeacherCollege = ref(''), recordScopeCollege = ref(''), recordSort = ref('COLLEGE')
const editor = ref<HTMLElement | null>(null)
const filters = ref({ college_org_id: '', major: '', grade: '', class_name: '', q: '' })
const page = ref(1), pageSize = 50
const isSchool = computed(() => session.activeRole === 'AUTH_ADMIN')
const roles = computed<Role[]>(() => isSchool.value ? ['COLLEGE_ADMIN'] : ['COUNSELOR', 'IDEOLOGY'])
const teachers = computed(() => users.value.filter(u => u.identity_types.includes('TEACHER')))
const visibleTeachers = computed(() => teachers.value.filter(u => (isSchool.value || !teacherCollege.value || u.college_org_id === teacherCollege.value) && `${u.display_name} ${u.school_id}`.toLowerCase().includes(teacherQuery.value.toLowerCase())))
const selectedTeacher = computed(() => teachers.value.find(u => u.user_id === selectedUser.value))
const current = computed(() => grants.value.find(g => g.user_id === selectedUser.value && g.role === role.value && g.active))
const collegeOptions = computed(() => Array.from(new Map(allStudents.value.map(s => [s.college_org_id, s.college_name])).entries()))
const visibleColleges = computed(() => collegeOptions.value.filter(([, name]) => name.toLowerCase().includes(collegeQuery.value.trim().toLowerCase())))
const collegeName = (id: string) => collegeOptions.value.find(c => c[0] === id)?.[1] ?? id
const teacherName = (g: RoleGrant) => users.value.find(u => u.user_id === g.user_id)?.display_name ?? g.user_id
const teacherCollegeName = (g: RoleGrant) => collegeName(users.value.find(u => u.user_id === g.user_id)?.college_org_id ?? '')
const studentColleges = computed(() => new Map(allStudents.value.map(s => [s.student_id, s.college_org_id])))
const scopeColleges = (g: RoleGrant) => [...new Set([...g.college_org_ids, ...g.student_ids.map(id => studentColleges.value.get(id)).filter((id): id is string => !!id)])]
const scopeLabel = (g: RoleGrant) => g.role === 'CAMPUS' ? '全校' : scopeColleges(g).map(collegeName).sort((a,b) => a.localeCompare(b, 'zh-CN')).join('、') || '未分配学院'
const studentRole = computed(() => role.value === 'COUNSELOR' || role.value === 'IDEOLOGY')
const filtered = computed(() => allStudents.value.filter(s => Object.entries(filters.value).every(([key, value]) => !value || (key === 'q' ? `${s.display_name} ${s.school_id}`.toLowerCase().includes(value.toLowerCase()) : s[key as keyof StudentDirectoryItem] === value))))
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const option = (key: 'major' | 'grade' | 'class_name') => Array.from(new Set(allStudents.value.filter(s => !filters.value.college_org_id || s.college_org_id === filters.value.college_org_id).map(s => s[key]))).sort()
const added = computed(() => picked.value.filter(id => !current.value?.student_ids.includes(id)).length)
const removed = computed(() => (current.value?.student_ids ?? []).filter(id => !picked.value.includes(id)).length)
const records = computed(() => grants.value.filter(g => {
  const user = users.value.find(u => u.user_id === g.user_id)
  const query = recordQuery.value.trim().toLowerCase()
  return roles.value.includes(g.role)
    && (!recordStatus.value || g.active === (recordStatus.value === 'ACTIVE'))
    && (!recordRole.value || g.role === recordRole.value)
    && (!recordTeacherCollege.value || user?.college_org_id === recordTeacherCollege.value)
    && (!recordScopeCollege.value || g.role === 'CAMPUS' || scopeColleges(g).includes(recordScopeCollege.value))
    && `${teacherName(g)} ${user?.school_id ?? ''} ${ROLE_LABEL[g.role]} ${teacherCollegeName(g)} ${scopeLabel(g)}`.toLowerCase().includes(query)
}).sort((a, b) => {
  const text = (g: RoleGrant) => recordSort.value === 'ROLE' ? ROLE_LABEL[g.role] : recordSort.value === 'TEACHER' ? teacherName(g) : scopeLabel(g)
  return (recordSort.value === 'STATUS' ? Number(b.active) - Number(a.active) : text(a).localeCompare(text(b), 'zh-CN'))
    || teacherName(a).localeCompare(teacherName(b), 'zh-CN') || a.id.localeCompare(b.id)
}))
function editGrant(g: RoleGrant) {
  selectedUser.value = g.user_id; role.value = g.role; hydrate()
  editor.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function hydrate() { picked.value = [...(current.value?.student_ids ?? [])]; colleges.value = [...(current.value?.college_org_ids ?? [])]; reviewing.value = false; collegeQuery.value = '' }
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
const cancelReview = ref<HTMLElement | null>(null)
async function requestCancel(g: RoleGrant) {
  revokeTarget.value = g
  await nextTick()
  cancelReview.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}
async function revoke() {
  if (!revokeTarget.value) return
  busy.value = true
  try { await api.revokeGrant(revokeTarget.value.id); message.value = '已取消该项负责职责及负责关系，目标人员的现有会话已失效。'; revokeTarget.value = null; await load() }
  catch(e) { message.value = describeError(e) } finally { busy.value = false }
}
onMounted(load)
</script>
<template><div class="stack permissions-view">
  <section class="panel"><h1>{{ isSchool ? '查看学院负责人' : '本学院教师与负责关系' }}</h1><p>{{ isSchool ? '从全校教师中任命学院负责人；辅导员、思政教师及班级学生范围由学院负责人配置。' : '为本院教师配置工作职责，并按班级分配负责学生。' }}</p><p v-if="message" role="status">{{ message }}</p><p v-if="busy">正在处理……</p></section>
  <section ref="editor" class="panel"><h2>1. 选择教师与工作职责</h2>
    <div class="manage-grid"><label v-if="!isSchool">教师所属学院<select v-model="teacherCollege"><option value="">全部授权学院</option><option v-for="[id,name] in collegeOptions" :key="id" :value="id">{{ name }}</option></select></label><label>{{ isSchool ? '搜索全校教师' : '查找教师' }}<input v-model="teacherQuery" placeholder="姓名或工号"></label><label>教师<select v-model="selectedUser" :disabled="busy"><option value="">请选择</option><option v-for="u in visibleTeachers" :key="u.user_id" :value="u.user_id">{{ u.display_name }} · {{ u.school_id }}</option></select></label><label>工作职责<select v-model="role" :disabled="busy"><option v-for="r in roles" :key="r" :value="r">{{ ROLE_LABEL[r] }}</option></select></label></div>
    <p v-if="selectedTeacher">当前选择：{{ selectedTeacher.display_name }} · {{ selectedTeacher.position_title }}；{{ current ? '正在编辑现有职责' : '将新增此职责' }}。</p>
  </section>
  <section class="panel"><h2>2. 明确管理范围</h2>
    <div v-if="role==='COLLEGE_ADMIN'">
      <details class="college-picker"><summary>选择管理学院（已选 {{ colleges.length }} 个）</summary><label>搜索学院<input v-model="collegeQuery" placeholder="输入学院名称" :disabled="busy"></label><div class="manage-students"><label v-for="[id,name] in visibleColleges" :key="id"><input v-model="colleges" type="checkbox" :value="id" :disabled="busy">{{ name }}</label><p v-if="!visibleColleges.length">没有匹配的学院。</p></div></details>
      <div class="manage-actions"><span v-if="!colleges.length">尚未选择管理学院</span><button v-for="id in colleges" :key="id" :disabled="busy" :aria-label="`移除${collegeName(id)}管理范围`" @click="colleges=colleges.filter(value=>value!==id)">{{ collegeName(id) }} ×</button></div>
      <p>支持多选；搜索只改变显示，已选学院会保留。移除部分学院后，请预览并保存变更。</p>
    </div>
    <p v-else-if="role==='CAMPUS'">园区职责提供全校查询、宿管账号和值班管理。学生风险通知仍只投递负责教师与当班宿管。</p>
    <template v-else-if="studentRole"><div class="manage-grid"><label>学院<select v-model="filters.college_org_id"><option value="">全部授权学院</option><option v-for="[id,name] in collegeOptions" :key="id" :value="id">{{ name }}</option></select></label><label v-for="key in (['major','grade','class_name'] as const)" :key="key">{{ {major:'专业',grade:'年级',class_name:'班级'}[key] }}<select v-model="filters[key]"><option value="">全部</option><option v-for="v in option(key)" :key="v" :value="v">{{ v }}</option></select></label><label>查找学生<input v-model="filters.q" placeholder="姓名或学号"></label></div>
      <div class="manage-actions"><strong>已选 {{ picked.length }} 人</strong><span>筛选结果 {{ filtered.length }} 人</span><button :disabled="busy || !filtered.length" @click="selectFiltered">加入全部筛选结果</button><button :disabled="busy || !filtered.length" @click="removeFiltered">移除筛选结果</button><button :disabled="busy" @click="hydrate">恢复已保存范围</button></div>
      <p>筛选只改变显示；“加入全部筛选结果”覆盖全部 {{ pages }} 页。其他筛选下已选的学生会保留。</p>
      <div class="manage-students"><label v-for="s in paged" :key="s.student_id"><input v-model="picked" type="checkbox" :value="s.student_id" :disabled="busy">{{ s.school_id }} {{ s.display_name }} · {{ s.college_name }} · {{ s.class_name }}</label><p v-if="!filtered.length">当前条件下没有学生。</p></div>
      <div class="manage-actions"><button :disabled="page<=1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page>=pages" @click="page++">下一页</button></div>
    </template>
  </section>
  <section class="panel"><h2>3. 核对并保存</h2><button v-if="current" :disabled="busy" @click="requestCancel(current)">取消当前职责的全部负责关系</button><p>保存会替换该教师此项职责的完整范围；其他职责保持各自授权。目标人员的现有会话将失效。</p>
    <button v-if="!reviewing" :disabled="busy || !selectedTeacher || (role==='COLLEGE_ADMIN' && !colleges.length)" @click="reviewing=true">预览本次变更</button>
    <div v-else class="manage-review"><p><strong>{{ selectedTeacher?.display_name }} · {{ ROLE_LABEL[role] }}</strong></p><p v-if="studentRole">负责 {{ picked.length }} 名学生，较当前新增 {{ added }} 人、移除 {{ removed }} 人。</p><p v-else-if="role==='COLLEGE_ADMIN'">管理学院：{{ colleges.map(id=>collegeOptions.find(c=>c[0]===id)?.[1]).join('、') }}</p><p v-else>管理范围：园区全校授权。</p><div class="manage-actions"><button :disabled="busy" @click="save">确认保存职责与范围</button><button :disabled="busy" @click="reviewing=false">继续修改</button></div></div>
  </section>
  <details class="panel"><summary>{{ isSchool ? '学院负责人记录' : '现有职责记录' }}（{{ grants.filter(g=>roles.includes(g.role)).length }} 条，点击展开）</summary>
    <div class="manage-grid">
      <label>状态<select v-model="recordStatus"><option value="ACTIVE">有效</option><option value="INACTIVE">已取消</option><option value="">全部状态</option></select></label>
      <label>职责身份<select v-model="recordRole"><option value="">全部职责</option><option v-for="r in roles" :key="r" :value="r">{{ ROLE_LABEL[r] }}</option></select></label>
      <label>教师所属学院<select v-model="recordTeacherCollege"><option value="">全部授权学院</option><option v-for="[id,name] in collegeOptions" :key="id" :value="id">{{ name }}</option></select></label>
      <label>管理范围学院<select v-model="recordScopeCollege"><option value="">全部授权学院</option><option v-for="[id,name] in collegeOptions" :key="id" :value="id">{{ name }}</option></select></label>
      <label>排序<select v-model="recordSort"><option value="COLLEGE">管理学院</option><option value="TEACHER">教师姓名</option><option value="ROLE">职责身份</option><option value="STATUS">有效状态优先</option></select></label>
      <label>搜索记录<input v-model="recordQuery" placeholder="姓名、工号、职责或学院"></label>
    </div><p>符合条件 {{ records.length }} 条；学院、姓名和职责按中文升序排列。全校职责包含各学院。</p>
    <div class="manage-table"><table><thead><tr><th>教师 / 所属学院</th><th>职责</th><th>管理范围</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="g in records" :key="g.id"><td>{{ teacherName(g) }}<br>{{ teacherCollegeName(g) }}</td><td>{{ ROLE_LABEL[g.role] }}</td><td>{{ scopeLabel(g) }}<span v-if="['COUNSELOR','IDEOLOGY'].includes(g.role)"> · {{ g.student_ids.length }} 名学生</span></td><td>{{ g.active?'有效':'已取消' }}</td><td><button :disabled="busy" @click="editGrant(g)">{{ g.active ? '编辑负责范围' : '重新配置' }}</button> <button v-if="g.active" :disabled="busy" @click="requestCancel(g)">取消负责</button></td></tr><tr v-if="!records.length"><td colspan="5">当前筛选条件下没有职责记录。</td></tr></tbody></table></div>
  </details>
  <section v-if="revokeTarget" ref="cancelReview" class="panel manage-review" role="region" aria-label="确认取消负责"><h2>确认取消负责</h2><p>确认取消 {{ teacherName(revokeTarget) }} 的{{ ROLE_LABEL[revokeTarget.role] }}职责？</p><p>管理范围：{{ scopeLabel(revokeTarget) }}<span v-if="['COUNSELOR','IDEOLOGY'].includes(revokeTarget.role)">，共 {{ revokeTarget.student_ids.length }} 名学生</span>。该项职责及其负责关系将一并取消，现有会话立即失效；其他职责不变，历史审计保留。</p><div class="manage-actions"><button :disabled="busy" @click="revoke">确认取消负责</button><button :disabled="busy" @click="revokeTarget=null">保留负责关系</button></div></section>
  <details class="panel"><summary>查看权限变更审计（{{ audit.length }} 条）</summary><p v-for="a in audit" :key="String(a.id)">{{ a.created_at }} · {{ a.action }} · {{ a.target }}</p><p v-if="!audit.length">暂无权限变更记录。</p></details>
</div></template>

<style scoped>
summary { cursor: pointer; font-weight: 600; }
.college-picker { border: 1px solid var(--line); border-radius: 10px; padding: 12px; }
.college-picker > label { display: flex; flex-direction: column; gap: 6px; margin-top: 12px; }
</style>

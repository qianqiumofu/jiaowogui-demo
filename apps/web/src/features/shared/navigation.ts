import type { Role } from '@/shared/api/types'

export interface NavItem {
  to: string
  name: string
  label: string
  stage?: string
  group?: string
}

const ITEMS: Array<NavItem & { roles: Role[]; action?: string }> = [
  { to: '/app/counselor/assistant', name: 'report-assistant', label: '报告助手', roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN'], action: 'agent:use' },
  { to: '/app/management', name: 'leadership', label: '管理工作台', roles: ['AUTH_ADMIN', 'COLLEGE_ADMIN', 'CAMPUS'] },
  { to: '/app/student/reservation', name: 'student-reservation', label: '晚归预约', roles: ['STUDENT'], action: 'reservation:create', stage: 'M2' },
  { to: '/app/student/records', name: 'student-records', label: '我的记录', roles: ['STUDENT'], stage: 'M2' },
  { to: '/app/counselor/students', name: 'counselor-students', label: '负责学生', roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN'], stage: 'M1' },
  { to: '/app/counselor/reports', name: 'counselor-reports', label: '查看晚归情况', roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN'], action: 'statistics:read', stage: 'M4' },
  { to: '/app/management/statistics', name: 'school-statistics', label: '查看晚归情况', roles: ['AUTH_ADMIN'], action: 'report:statistics' },
  { to: '/app/dorm/tonight', name: 'dorm-tonight', label: '今晚名单', roles: ['DORM_MANAGER'], stage: 'M2' },
  { to: '/app/dorm/manual-entry', name: 'dorm-manual-entry', label: '现场补录', roles: ['DORM_MANAGER'], stage: 'M3' },
  { to: '/app/campus/query', name: 'campus-query', label: '全校查询', roles: ['CAMPUS'], stage: 'M4' },
  { to: '/app/campus/staff-accounts', name: 'campus-staff-accounts', label: '宿管账号', roles: ['CAMPUS'], action: 'staff_account:read', stage: 'M1' },
  { to: '/app/campus/notifications', name: 'campus-notifications', label: '演示投递', roles: ['CAMPUS'], action: 'notification:dispatch', stage: 'M1' },
  { to: '/app/shared/inbox', name: 'shared-inbox', label: '模拟收件箱', roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN', 'DORM_MANAGER', 'CAMPUS'], action: 'notification:read', stage: 'M1' },
  { to: '/app/shared/risk', name: 'shared-risk', label: '风险跟进', roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN', 'DORM_MANAGER', 'CAMPUS'], action: 'risk:read', stage: 'M4' },
  { to: '/app/shared/records', name: 'shared-records', label: '返宿记录', roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN', 'DORM_MANAGER'], stage: 'M3' },
  { to: '/app/profile', name: 'profile', label: '我的身份', roles: ['STUDENT', 'DORM_MANAGER', 'COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN', 'AUTH_ADMIN', 'TEACHER', 'CAMPUS'] },
  { to: '/app/management/permissions', name: 'permissions', label: '权限与负责关系', roles: ['AUTH_ADMIN', 'COLLEGE_ADMIN'], action: 'permission:manage' },
  { to: '/app/campus/duties', name: 'duties', label: '宿管值班指派', roles: ['CAMPUS'], action: 'duty:assign' },
  { to: '/app/campus/risk-policy', name: 'risk-policy', label: '风险规则版本', roles: ['CAMPUS'], action: 'risk:config' },
  { to: '/app/guide', name: 'guide', label: '操作指南', roles: ['STUDENT', 'DORM_MANAGER', 'COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN', 'AUTH_ADMIN', 'TEACHER', 'CAMPUS'] },
  { to: '/app/settings', name: 'settings', label: '设置', roles: ['STUDENT', 'DORM_MANAGER', 'COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN', 'AUTH_ADMIN', 'TEACHER', 'CAMPUS'] },
]

export function navigationFor(role: Role | null, allowed: string[]): NavItem[] {
  if (!role) return []
  return ITEMS.filter(
    (item) => item.roles.includes(role) && (!item.action || allowed.includes(item.action)),
  ).map(({ to, name, label }) => ({ to, name, label: role === 'AUTH_ADMIN' && name === 'permissions' ? '查看学院负责人' : role === 'AUTH_ADMIN' && name === 'counselor-reports' ? '查看晚归情况' : role === 'COLLEGE_ADMIN' && name === 'counselor-students' ? '学院学生名册' : role === 'CAMPUS' && name === 'shared-risk' ? '风险主动查询' : label,
    group: name === 'leadership' ? '工作台' : ['permissions', 'campus-staff-accounts', 'duties', 'risk-policy'].includes(name) ? '人员与配置' : ['profile', 'guide', 'settings', 'campus-notifications'].includes(name) ? '帮助与演示' : '业务查看',
  })).sort((a,b) => ['工作台','业务查看','人员与配置','帮助与演示'].indexOf(a.group) - ['工作台','业务查看','人员与配置','帮助与演示'].indexOf(b.group))
}

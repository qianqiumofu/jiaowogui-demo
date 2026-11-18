import type { Role } from '@/shared/api/types'

export interface NavItem {
  to: string
  name: string
  label: string
  stage?: string
}

const ITEMS: Array<NavItem & { roles: Role[]; action?: string }> = [
  { to: '/app/student/reservation', name: 'student-reservation', label: '晚归预约', roles: ['STUDENT'], action: 'reservation:create', stage: 'M2' },
  { to: '/app/student/records', name: 'student-records', label: '我的返宿记录', roles: ['STUDENT'], stage: 'M3' },
  { to: '/app/counselor/students', name: 'counselor-students', label: '负责学生', roles: ['COUNSELOR'], stage: 'M1' },
  { to: '/app/counselor/reports', name: 'counselor-reports', label: '日报与周报', roles: ['COUNSELOR'], stage: 'M4' },
  { to: '/app/dorm/tonight', name: 'dorm-tonight', label: '今晚名单', roles: ['DORM_MANAGER'], stage: 'M2' },
  { to: '/app/dorm/manual-entry', name: 'dorm-manual-entry', label: '现场补录', roles: ['DORM_MANAGER'], stage: 'M3' },
  { to: '/app/campus/query', name: 'campus-query', label: '全校查询', roles: ['CAMPUS'], stage: 'M4' },
  { to: '/app/campus/staff-accounts', name: 'campus-staff-accounts', label: '宿管账号', roles: ['CAMPUS'], action: 'staff_account:read', stage: 'M1' },
  { to: '/app/campus/notifications', name: 'campus-notifications', label: '演示投递', roles: ['CAMPUS'], action: 'notification:dispatch', stage: 'M1' },
  { to: '/app/shared/inbox', name: 'shared-inbox', label: '模拟收件箱', roles: ['COUNSELOR', 'DORM_MANAGER', 'CAMPUS'], action: 'notification:read', stage: 'M1' },
  { to: '/app/shared/risk', name: 'shared-risk', label: '风险跟进', roles: ['COUNSELOR', 'DORM_MANAGER', 'CAMPUS'], action: 'risk:read', stage: 'M4' },
  { to: '/app/shared/records', name: 'shared-records', label: '返宿记录', roles: ['COUNSELOR', 'DORM_MANAGER'], stage: 'M3' },
  { to: '/app/guide', name: 'guide', label: '操作指南', roles: ['STUDENT', 'DORM_MANAGER', 'COUNSELOR', 'CAMPUS'] },
  { to: '/app/settings', name: 'settings', label: '设置', roles: ['STUDENT', 'DORM_MANAGER', 'COUNSELOR', 'CAMPUS'] },
]

export function navigationFor(role: Role | null, allowed: string[]): NavItem[] {
  if (!role) return []
  return ITEMS.filter(
    (item) => item.roles.includes(role) && (!item.action || allowed.includes(item.action)),
  ).map(({ to, name, label, stage }) => ({ to, name, label, stage }))
}

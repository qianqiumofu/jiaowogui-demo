import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import AppShell from '@/shared/components/AppShell.vue'
import type { Role } from '@/shared/api/types'
import { useSessionStore } from '@/shared/stores/session'

const HOME_BY_ROLE: Record<Role, string> = {
  STUDENT: 'student-reservation',
  COUNSELOR: 'counselor-students',
  DORM_MANAGER: 'dorm-tonight',
  CAMPUS: 'campus-query',
  TEACHER: 'profile',
  IDEOLOGY: 'counselor-students',
  COLLEGE_ADMIN: 'counselor-students',
  AUTH_ADMIN: 'permissions',
}

function homeTarget(): string {
  const session = useSessionStore()
  if (!session.context) return 'login'
  return HOME_BY_ROLE[session.context.active_role]
}

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'login', component: () => import('@/features/auth/views/LoginView.vue'), meta: { public: true } },
  {
    path: '/app',
    component: AppShell,
    children: [
      { path: '', name: 'home', redirect: () => ({ name: homeTarget() }) },
      {
        path: 'student/reservation',
        name: 'student-reservation',
        component: () => import('@/features/student/views/ReservationView.vue'),
        meta: { roles: ['STUDENT'], label: '晚归预约', action: 'reservation:create' },
      },
      {
        path: 'student/records',
        name: 'student-records',
        component: () => import('@/features/student/views/MyRecordsView.vue'),
        meta: { roles: ['STUDENT'], label: '我的返宿记录' },
      },
      {
        path: 'counselor/students',
        name: 'counselor-students',
        component: () => import('@/features/counselor/views/StudentsView.vue'),
        meta: { roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN'], label: '负责学生' },
      },
      {
        path: 'counselor/reports',
        name: 'counselor-reports',
        component: () => import('@/features/counselor/views/ReportsView.vue'),
        meta: { roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN'], label: '日报与周报' },
      },
      {
        path: 'dorm/tonight',
        name: 'dorm-tonight',
        component: () => import('@/features/dorm-manager/views/TonightView.vue'),
        meta: { roles: ['DORM_MANAGER'], label: '今晚名单' },
      },
      {
        path: 'dorm/manual-entry',
        name: 'dorm-manual-entry',
        component: () => import('@/features/dorm-manager/views/ManualEntryView.vue'),
        meta: { roles: ['DORM_MANAGER'], label: '现场补录' },
      },
      {
        path: 'campus/query',
        name: 'campus-query',
        component: () => import('@/features/campus/views/QueryView.vue'),
        meta: { roles: ['CAMPUS'], label: '全校查询' },
      },
      {
        path: 'campus/staff-accounts',
        name: 'campus-staff-accounts',
        component: () => import('@/features/campus/views/StaffAccountsView.vue'),
        meta: { roles: ['CAMPUS'], label: '宿管账号', action: 'staff_account:read' },
      },
      {
        path: 'campus/notifications',
        name: 'campus-notifications',
        component: () => import('@/features/campus/views/NotificationDemoView.vue'),
        meta: { roles: ['CAMPUS'], label: '演示投递', action: 'notification:dispatch' },
      },
      {
        path: 'shared/inbox',
        name: 'shared-inbox',
        component: () => import('@/features/shared/views/InboxView.vue'),
        meta: {
          roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN', 'DORM_MANAGER', 'CAMPUS'],
          label: '模拟收件箱',
          action: 'notification:read',
        },
      },
      {
        path: 'shared/risk',
        name: 'shared-risk',
        component: () => import('@/features/shared/views/RiskView.vue'),
        meta: { roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN', 'DORM_MANAGER', 'CAMPUS'], label: '风险跟进', action: 'risk:read' },
      },
      {
        path: 'shared/records',
        name: 'shared-records',
        component: () => import('@/features/shared/views/RecordsView.vue'),
        meta: { roles: ['COUNSELOR', 'IDEOLOGY', 'COLLEGE_ADMIN', 'DORM_MANAGER'], label: '返宿记录' },
      },
      { path: 'profile', name: 'profile', component: () => import('@/features/management/views/ProfileView.vue'), meta: { label: '我的身份' } },
      { path: 'management/permissions', name: 'permissions', component: () => import('@/features/management/views/PermissionsView.vue'), meta: { roles: ['AUTH_ADMIN', 'COLLEGE_ADMIN'], label: '权限与负责关系', action: 'permission:manage' } },
      { path: 'campus/duties', name: 'duties', component: () => import('@/features/management/views/DutyView.vue'), meta: { roles: ['CAMPUS'], label: '宿管值班指派', action: 'duty:assign' } },
      { path: 'campus/risk-policy', name: 'risk-policy', component: () => import('@/features/management/views/PolicyView.vue'), meta: { roles: ['CAMPUS'], label: '风险规则版本', action: 'risk:config' } },
      {
        path: 'guide',
        name: 'guide',
        component: () => import('@/features/shared/views/GuideView.vue'),
        meta: { label: '操作指南' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/features/shared/views/SettingsView.vue'),
        meta: { label: '设置' },
      },
    ],
  },
  { path: '/terminal', name: 'terminal', component: () => import('@/features/gate-demo/views/GateDemoView.vue'), meta: { public: true, label: '门口终端' } },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/features/shared/views/NotFoundView.vue'), meta: { public: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const session = useSessionStore()
  if (!session.ready) return false
  const requiresLogin = to.matched.some((record) => !record.meta.public)
  if (requiresLogin && !session.context) return { name: 'login' }
  if (to.name === 'login' && session.context) return { name: 'home' }
  const roles = to.meta.roles as string[] | undefined
  if (roles && session.context && !roles.includes(session.context.active_role)) {
    return { name: 'home' }
  }
  return true
})

export default router

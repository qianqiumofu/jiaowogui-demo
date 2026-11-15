import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import AppShell from '@/shared/components/AppShell.vue'
import type { Role } from '@/shared/api/types'
import { useSessionStore } from '@/shared/stores/session'

const HOME_BY_ROLE: Record<Role, string> = {
  STUDENT: 'student-reservation',
  COUNSELOR: 'counselor-students',
  DORM_MANAGER: 'dorm-tonight',
  CAMPUS: 'campus-query',
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
        meta: { roles: ['COUNSELOR'], label: '负责学生' },
      },
      {
        path: 'counselor/reports',
        name: 'counselor-reports',
        component: () => import('@/features/counselor/views/ReportsView.vue'),
        meta: { roles: ['COUNSELOR'], label: '日报与周报' },
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
        path: 'shared/risk',
        name: 'shared-risk',
        component: () => import('@/features/shared/views/RiskView.vue'),
        meta: { roles: ['COUNSELOR', 'DORM_MANAGER', 'CAMPUS'], label: '风险跟进', action: 'risk:read' },
      },
      {
        path: 'shared/records',
        name: 'shared-records',
        component: () => import('@/features/shared/views/RecordsView.vue'),
        meta: { roles: ['COUNSELOR', 'DORM_MANAGER'], label: '返宿记录' },
      },
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

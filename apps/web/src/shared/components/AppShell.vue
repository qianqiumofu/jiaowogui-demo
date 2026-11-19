<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import ClockBadge from '@/shared/components/ClockBadge.vue'
import RoleSwitcher from '@/shared/components/RoleSwitcher.vue'
import SideNav from '@/shared/components/SideNav.vue'
import type { Scope } from '@/shared/api/types'
import { useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()
const route = useRoute()

const currentLabel = computed(() => (route.meta.label as string | undefined) ?? '')
const scopeHint = computed(() => {
  const scope = (session.context?.scope ?? {}) as Scope
  if (scope.student_id) return `本人范围：${scope.student_id}`
  if (session.activeRole === 'COLLEGE_ADMIN') return `获授学院 · ${scope.student_ids?.length ?? 0} 名学生`
  if (scope.building_ids?.length) return `值班楼栋：${scope.building_ids.join('、')}`
  if (scope.resolved_by?.startsWith('pending:')) return '范围待目录同步'
  if (scope.student_ids) return `负责学生：${scope.student_ids.length} 人`
  if (session.activeRole === 'TEACHER') return '本人身份信息'
  if (session.activeRole === 'AUTH_ADMIN') return '全校权限配置范围'
  return '全校授权范围'
})
</script>

<template>
  <div class="shell">
    <header class="shell__header">
      <div class="shell__brand">
        <span class="shell__mark">交我归</span>
        <span class="shell__sub">宿舍晚归管理 Demo</span>
      </div>
      <div class="shell__headerRight">
        <ClockBadge />
        <RouterLink class="shell__terminal" to="/terminal">门口终端</RouterLink>
        <RoleSwitcher />
      </div>
    </header>
    <div class="shell__body">
      <SideNav />
      <main class="shell__main">
        <div class="shell__crumbs">
          <strong>{{ currentLabel }}</strong>
          <span>{{ session.context?.display_name }} · {{ scopeHint }}</span>
        </div>
        <RouterView />
      </main>
    </div>
  </div>
</template>

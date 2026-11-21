<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import ClockBadge from '@/shared/components/ClockBadge.vue'
import RoleSwitcher from '@/shared/components/RoleSwitcher.vue'
import SideNav from '@/shared/components/SideNav.vue'
import type { Scope } from '@/shared/api/types'
import { api } from '@/shared/api/client'
import { useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()
const route = useRoute()
const buildingLabels = ref<Record<string, string>>({})

watch(() => [session.context?.session_id, session.context?.scope] as const, async () => {
  buildingLabels.value = {}
  const context = session.context
  if (session.activeRole !== 'DORM_MANAGER' || !context) return
  try {
    const [fixed, extra] = await Promise.all([api.dutyRoster(), api.duties()])
    if (session.context !== context) return
    buildingLabels.value = Object.fromEntries(
      [...fixed.items, ...extra.items].filter(row => row.building_name).map(row => [row.building_id, row.building_name!]),
    )
  } catch {
    // 范围仍由服务端校验；目录暂不可用时不把内部 ID 显示给用户。
  }
}, { immediate: true })

const currentLabel = computed(() => (route.meta.label as string | undefined) ?? '')
const scopeHint = computed(() => {
  const scope = (session.context?.scope ?? {}) as Scope
  if (scope.student_id) return `本人范围：${scope.student_id}`
  if (session.activeRole === 'COLLEGE_ADMIN') return `获授学院 · ${scope.student_ids?.length ?? 0} 名学生`
  if (scope.building_ids?.length) {
    const labels = scope.building_ids.map(id => buildingLabels.value[id]).filter(Boolean)
    return labels.length === scope.building_ids.length
      ? `值班楼栋：${labels.join('、')}` : `已授权 ${scope.building_ids.length} 栋楼`
  }
  if (session.activeRole === 'DORM_MANAGER') return '当前没有已授权的值班楼栋'
  if (scope.resolved_by?.startsWith('pending:')) return '范围待目录同步'
  if (session.activeRole === 'AUTH_ADMIN') return '学院负责人任免 · 全校晚归只读'
  if (scope.student_ids) return `负责学生：${scope.student_ids.length} 人`
  if (session.activeRole === 'TEACHER') return '本人身份信息'
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

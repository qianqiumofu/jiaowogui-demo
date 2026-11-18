<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { ROLE_LABEL, describeError, useSessionStore } from '@/shared/stores/session'
import type { Role } from '@/shared/api/types'

const session = useSessionStore()
const router = useRouter()

const roles = computed(() => session.context?.roles ?? [])

async function pick(role: Role) {
  if (!session.context || role === session.context.active_role) return
  try {
    await session.switchRole(role)
    await router.replace({ name: 'home' })
  } catch (cause) {
    session.error = describeError(cause)
  }
}

async function switchAccount() {
  try {
    await session.logout()
  } catch {
    // 会话可能已过期：store 的 finally 已清掉本地令牌，仍要回到账号选择页。
  } finally {
    await router.replace({ name: 'login' })
  }
}
</script>

<template>
  <div class="roleswitch">
    <div v-if="roles.length > 1" class="roleswitch__pill">
      <button
        v-for="role in roles"
        :key="role"
        class="roleswitch__btn"
        :class="{ 'roleswitch__btn--on': session.context?.active_role === role }"
        type="button"
        @click="pick(role)"
      >
        {{ ROLE_LABEL[role] }}
      </button>
    </div>
    <button class="roleswitch__account" type="button" @click="switchAccount">切换账号</button>
  </div>
</template>

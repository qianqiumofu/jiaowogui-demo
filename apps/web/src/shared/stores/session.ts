import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiRequestError, api, readToken, writeToken } from '@/shared/api/client'
import type { Role, SessionContext } from '@/shared/api/types'

export const ROLE_LABEL: Record<Role, string> = {
  STUDENT: '学生',
  DORM_MANAGER: '宿管',
  COUNSELOR: '辅导员',
  CAMPUS: '园区',
}

export const useSessionStore = defineStore('session', () => {
  const context = ref<SessionContext | null>(null)
  const allowedActions = ref<string[]>([])
  const ready = ref(false)
  const error = ref<string | null>(null)

  const activeRole = computed<Role | null>(() => context.value?.active_role ?? null)
  const can = computed(() => (action: string) => allowedActions.value.includes(action))
  const roleLabel = computed(() => (activeRole.value ? ROLE_LABEL[activeRole.value] : '未登录'))

  async function restore(): Promise<void> {
    error.value = null
    if (!readToken()) {
      ready.value = true
      return
    }
    try {
      const [me, actions] = await Promise.all([api.me(), api.allowedActions()])
      context.value = me
      allowedActions.value = actions.allowed_actions
    } catch (cause) {
      writeToken(null)
      context.value = null
      allowedActions.value = []
      error.value = describe(cause)
    } finally {
      ready.value = true
    }
  }

  async function login(loginName: string, password: string): Promise<void> {
    const session = await api.login(loginName, password)
    context.value = session.session
    await refreshActions()
  }

  async function switchRole(role: Role): Promise<void> {
    const session = await api.switchRole(role)
    context.value = session.session
    await refreshActions()
  }

  async function logout(): Promise<void> {
    try {
      await api.logout()
    } finally {
      context.value = null
      allowedActions.value = []
      writeToken(null)
    }
  }

  async function refreshActions(): Promise<void> {
    allowedActions.value = (await api.allowedActions()).allowed_actions
  }

  function clearError(): void {
    error.value = null
  }

  return {
    context,
    allowedActions,
    ready,
    error,
    activeRole,
    roleLabel,
    can,
    restore,
    login,
    switchRole,
    logout,
    clearError,
  }
})

export function describeError(cause: unknown): string {
  return cause instanceof ApiRequestError ? `${cause.code}：${cause.message}` : String(cause)
}

function describe(cause: unknown): string {
  return describeError(cause)
}

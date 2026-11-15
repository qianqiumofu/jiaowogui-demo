<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiRequestError, api } from '@/shared/api/client'
import type { DemoAccount } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const accounts = ref<DemoAccount[]>([])
const loading = ref(true)
const busy = ref<string | null>(null)
const session = useSessionStore()
const router = useRouter()

const ROLE_TEXT: Record<string, string> = {
  STUDENT: '学生',
  DORM_MANAGER: '宿管',
  COUNSELOR: '辅导员',
  CAMPUS: '园区',
}

onMounted(async () => {
  try {
    accounts.value = await api.demoAccounts()
  } catch (cause) {
    session.error = cause instanceof ApiRequestError ? describeError(cause) : String(cause)
  } finally {
    loading.value = false
  }
})

async function enter(account: DemoAccount) {
  busy.value = account.login_name
  try {
    await session.login(account.login_name, account.password)
    await router.replace({ name: 'home' })
  } catch (cause) {
    session.error = describeError(cause)
  } finally {
    busy.value = null
  }
}

</script>

<template>
  <div class="login">
    <div>
      <p class="login__mark">交我归</p>
      <p class="login__sub">宿舍晚归管理演示。选择一个合成账号进入。</p>
    </div>

    <div class="login__grid">
      <p v-if="loading" class="login__hint">读取账号中……</p>
      <button
        v-for="account in accounts"
        :key="account.login_name"
        class="login__card"
        type="button"
        :disabled="busy !== null"
        @click="enter(account)"
      >
        <span>
          <span class="login__name">{{ account.display_name }}</span>
          <span class="login__roles">
            {{ account.roles.map((role) => ROLE_TEXT[role]).join(' / ') }} · 口令 {{ account.password }}
          </span>
        </span>
        <span class="login__hint">{{ busy === account.login_name ? '进入中' : '' }}</span>
      </button>
    </div>

    <RouterLink class="login__terminalLink" to="/terminal">门口终端模拟入口</RouterLink>
  </div>
</template>

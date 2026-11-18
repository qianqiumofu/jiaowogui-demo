<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiRequestError, api } from '@/shared/api/client'
import type { DemoAccount } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const accounts = ref<DemoAccount[]>([])
const loading = ref(true)
const busy = ref<string | null>(null)
const session = useSessionStore()
const router = useRouter()

const staffLogin = ref({ login_name: '', password: '' })
const staffBusy = ref(false)

const ROLE_TEXT: Record<string, string> = {
  STUDENT: '学生',
  DORM_MANAGER: '宿管',
  COUNSELOR: '辅导员',
  CAMPUS: '园区',
}

const unified = computed(() =>
  accounts.value.filter((item) => item.account_source === 'UNIFIED_SCHOOL'),
)
const localStaff = computed(() =>
  accounts.value.filter((item) => item.account_source === 'STAFF_LOCAL'),
)

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

async function enterWithStaffAccount() {
  staffBusy.value = true
  try {
    await session.login(staffLogin.value.login_name.trim(), staffLogin.value.password)
    await router.replace({ name: 'home' })
  } catch (cause) {
    session.error = describeError(cause)
  } finally {
    staffBusy.value = false
  }
}
</script>

<template>
  <div class="login">
    <div>
      <p class="login__mark">交我归</p>
      <p class="login__sub">宿舍晚归管理演示。校内人员用统一身份，工号账号用园区下发的口令。</p>
    </div>

    <section class="login__group">
      <h2 class="login__groupTitle">校内统一身份</h2>
      <p class="login__line">学生、辅导员与园区使用者共用统一账户，正式版由后端自动识别身份。</p>
      <div class="login__grid">
        <p v-if="loading" class="login__hint">读取账号中……</p>
        <button
          v-for="account in unified"
          :key="account.login_name"
          class="login__card"
          type="button"
          :disabled="busy !== null"
          @click="enter(account)"
        >
          <span>
            <span class="login__name">{{ account.display_name }}</span>
            <span class="login__roles">
              {{ account.roles.map((role) => ROLE_TEXT[role]).join(' / ') }} · {{ account.email }}
            </span>
          </span>
          <span class="login__hint">{{ busy === account.login_name ? '进入中' : '' }}</span>
        </button>
      </div>
    </section>

    <section class="login__group">
      <h2 class="login__groupTitle">园区分发的工作账号</h2>
      <p class="login__line">宿管属雇佣人员，没有校内账户，账号与楼栋范围由园区注册下发。</p>
      <div class="login__grid">
        <button
          v-for="account in localStaff"
          :key="account.login_name"
          class="login__card"
          type="button"
          :disabled="busy !== null"
          @click="enter(account)"
        >
          <span>
            <span class="login__name">{{ account.display_name }}</span>
            <span class="login__roles">工号 {{ account.login_name }} · 演示种子口令</span>
          </span>
          <span class="login__hint">{{ busy === account.login_name ? '进入中' : '' }}</span>
        </button>
      </div>

      <form class="login__form" @submit.prevent="enterWithStaffAccount">
        <label class="login__field">
          <span class="login__fieldLabel">工号账号</span>
          <input v-model="staffLogin.login_name" autocomplete="username" placeholder="例如 dorm_a2" />
        </label>
        <label class="login__field">
          <span class="login__fieldLabel">初始口令</span>
          <input
            v-model="staffLogin.password"
            type="password"
            autocomplete="current-password"
            placeholder="园区下发的一次性口令"
          />
        </label>
        <button class="login__submit" type="submit" :disabled="staffBusy || !staffLogin.login_name || !staffLogin.password">
          {{ staffBusy ? '登录中' : '用工号登录' }}
        </button>
      </form>
    </section>

    <RouterLink class="login__terminalLink" to="/terminal">门口终端模拟入口</RouterLink>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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
  CAMPUS: '园区负责人',
  IDEOLOGY: '专职思政',
  TEACHER: '教师',
  COLLEGE_ADMIN: '学院负责人',
  AUTH_ADMIN: '校级权限管理',
}

const query = ref(''), selectedRole = ref(''), page = ref(1)
const filtered = computed(() => accounts.value.filter(a => `${a.display_name} ${a.login_name}`.toLowerCase().includes(query.value.toLowerCase()) && (!selectedRole.value || a.roles.some(r => r === selectedRole.value))))
const unifiedAll = computed(() => filtered.value.filter(a => a.account_source === 'UNIFIED_SCHOOL'))
const staffAll = computed(() => filtered.value.filter(a => a.account_source === 'STAFF_LOCAL'))
const pages = computed(() => Math.max(1, Math.ceil(Math.max(unifiedAll.value.length, staffAll.value.length) / 12)))
const unified = computed(() => unifiedAll.value.slice((page.value-1)*12,page.value*12))
const localStaff = computed(() => staffAll.value.slice((page.value-1)*12,page.value*12))
watch([query, selectedRole], () => { page.value = 1 })

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
      <h2 class="login__groupTitle">选择体验身份</h2>
      <p class="login__line">领导体验建议从校级权限管理、学院负责人或园区负责人开始。</p>
      <div class="manage-grid"><label>工作身份<select v-model="selectedRole"><option value="">全部身份</option><option v-for="(label,key) in ROLE_TEXT" :key="key" :value="key">{{ label }}</option></select></label><label>查找账号<input v-model="query" placeholder="例如：数学学院、A2、college_admin"></label></div>
      <div class="manage-actions"><span>找到 {{ filtered.length }} 个体验账号 · {{ page }} / {{ pages }} 页</span><button :disabled="page<=1" @click="page--">上一页</button><button :disabled="page>=pages" @click="page++">下一页</button></div>
    </section>
    <section class="login__group" v-if="unified.length || loading">
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

      <p class="login__line">也可输入其他合成账号（如 student_0201）与演示口令登录学生或教师身份。</p>
      <form class="login__form" @submit.prevent="enterWithStaffAccount">
        <label class="login__field">
          <span class="login__fieldLabel">合成登录账号</span>
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
          {{ staffBusy ? '登录中' : '使用账号登录' }}
        </button>
      </form>
    </section>

    <RouterLink class="login__terminalLink" to="/terminal">门口终端模拟入口</RouterLink>
  </div>
</template>

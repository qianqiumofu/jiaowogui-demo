<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '@/shared/api/client'
import type { StaffAccount } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()
const items = ref<StaffAccount[]>([])
const loading = ref(true)
const busy = ref<string | null>(null)
const notice = ref<{ text: string; bad: boolean } | null>(null)

const draft = ref({ login_name: '', display_name: '', buildings: '' })
const rebindFor = ref<string | null>(null)
const rebindBuildings = ref('')

function tokens(raw: string): string[] {
  return raw
    .split(/[,，\s]+/)
    .map((value) => value.trim())
    .filter(Boolean)
}

async function load() {
  loading.value = true
  try {
    items.value = (await api.staffAccounts()).items
  } catch (cause) {
    notice.value = { text: describeError(cause), bad: true }
  } finally {
    loading.value = false
  }
}

function fail(cause: unknown) {
  notice.value = { text: describeError(cause), bad: true }
}

async function create() {
  busy.value = 'create'
  notice.value = null
  try {
    const created = await api.createStaffAccount({
      login_name: draft.value.login_name.trim(),
      display_name: draft.value.display_name.trim(),
      building_ids: tokens(draft.value.buildings),
    })
    draft.value = { login_name: '', display_name: '', buildings: '' }
    // 初始口令只在这里出现一次，交由园区当面下发。
    notice.value = {
      text: `已创建 ${created.account.login_name}，初始口令 ${created.initial_password}，只显示这一次。`,
      bad: false,
    }
    await load()
  } catch (cause) {
    fail(cause)
  } finally {
    busy.value = null
  }
}

async function rebind(id: string) {
  busy.value = id
  notice.value = null
  try {
    await api.updateStaffAccount(id, { building_ids: tokens(rebindBuildings.value) })
    rebindFor.value = null
    await load()
  } catch (cause) {
    fail(cause)
  } finally {
    busy.value = null
  }
}

async function reset(id: string) {
  busy.value = id
  notice.value = null
  try {
    const result = await api.resetStaffPassword(id)
    notice.value = {
      text: `${result.account.login_name} 的新口令 ${result.initial_password}，旧会话已失效。`,
      bad: false,
    }
  } catch (cause) {
    fail(cause)
  } finally {
    busy.value = null
  }
}

async function disable(id: string) {
  busy.value = id
  notice.value = null
  try {
    await api.disableStaffAccount(id)
    await load()
  } catch (cause) {
    fail(cause)
  } finally {
    busy.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="stack">
    <section class="panel">
      <div class="panel__head">
        <h2>宿管工号账号</h2>
        <button class="panel__reload" type="button" @click="load">刷新</button>
      </div>
      <p class="panel__line">
        宿管是雇佣人员，不走校内统一身份；在此注册账号、绑定固定管理楼栋并下发口令（R19）。
      </p>

      <p v-if="notice" class="resv__notice" :class="{ 'resv__notice--bad': notice.bad }">{{ notice.text }}</p>

      <ul v-if="items.length" class="staff__list">
        <li v-for="item in items" :key="item.id" class="staff__row">
          <div class="staff__main">
            <span class="staff__name">{{ item.display_name }}</span>
            <span class="staff__login">工号 {{ item.login_name }}</span>
            <span class="staff__tag" :class="{ 'staff__tag--off': item.status !== 'ACTIVE' }">
              {{ item.status === 'ACTIVE' ? '在用' : '已停用' }}
            </span>
          </div>
          <div class="staff__buildings">
            <span v-for="building in item.building_ids" :key="building" class="staff__building">{{ building }}</span>
          </div>
          <div v-if="rebindFor === item.id" class="staff__rebind">
            <input v-model="rebindBuildings" placeholder="用空格或逗号分隔楼栋编号" />
            <button
              class="resv__primary"
              type="button"
              :disabled="busy === item.id"
              @click="rebind(item.id)"
            >
              保存
            </button>
            <button class="resv__ghost" type="button" @click="rebindFor = null">取消</button>
          </div>
          <div v-else class="staff__actions">
            <button
              class="resv__ghost"
              type="button"
              :disabled="busy !== null"
              @click="((rebindFor = item.id), (rebindBuildings = item.building_ids.join(', ')))"
            >
              改绑楼栋
            </button>
            <button
              class="resv__ghost"
              type="button"
              :disabled="busy !== null || item.status !== 'ACTIVE'"
              @click="reset(item.id)"
            >
              重置口令
            </button>
            <button
              class="resv__ghost"
              type="button"
              :disabled="busy !== null || item.status !== 'ACTIVE'"
              @click="disable(item.id)"
            >
              停用
            </button>
          </div>
        </li>
      </ul>
      <p v-else-if="loading" class="panel__placeholder">读取账号中……</p>
      <p v-else class="panel__placeholder">还没有工号账号。为负责的楼栋创建一个，阿姨用初始口令登录。</p>
    </section>

    <section class="panel">
      <div class="panel__head">
        <h2>新注册</h2>
      </div>
      <form class="resv__form" @submit.prevent="create">
        <label class="resv__field">
          <span class="resv__label">登录名</span>
          <input v-model="draft.login_name" placeholder="例如 dorm_a2" required />
        </label>
        <label class="resv__field">
          <span class="resv__label">显示名</span>
          <input v-model="draft.display_name" placeholder="例如 刘阿姨" required />
        </label>
        <label class="resv__field resv__field--wide">
          <span class="resv__label">固定管理楼栋</span>
          <input v-model="draft.buildings" placeholder="bldg_a2" required />
        </label>
        <div class="resv__actions">
          <button
            class="resv__primary"
            type="submit"
            :disabled="busy !== null || !session.can('staff_account:create')"
          >
            {{ busy === 'create' ? '提交中' : '创建并生成初始口令' }}
          </button>
        </div>
      </form>
    </section>
  </div>
</template>

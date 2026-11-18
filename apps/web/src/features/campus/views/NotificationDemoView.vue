<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api } from '@/shared/api/client'
import type {
  NotificationJob,
  NotificationTemplate,
  Role,
  StaffAccount,
  DemoAccount,
} from '@/shared/api/types'
import { describeError } from '@/shared/stores/session'

/** 与后端 RECIPIENT_ROLES 对齐，只用于过滤可选收件人；放行与否仍由服务端判定。 */
const TEMPLATE_ROLES: Record<NotificationTemplate, Role[]> = {
  NIGHT_ROSTER: ['DORM_MANAGER'],
  DAILY_REPORT: ['COUNSELOR'],
  WEEKLY_REPORT: ['COUNSELOR'],
  RISK_ALERT: ['COUNSELOR', 'DORM_MANAGER'],
}

const TEMPLATE_LABELS: Record<NotificationTemplate, string> = {
  NIGHT_ROSTER: '23:30 宿管名单快照',
  DAILY_REPORT: '辅导员日报',
  WEEKLY_REPORT: '辅导员周报',
  RISK_ALERT: '风险跟进提示',
}

const STATUS_LABELS: Record<string, string> = {
  PENDING: '排队中',
  RUNNING: '消费中',
  DONE: '已完成',
  FAILED: '失败',
}

interface Recipient {
  id: string
  label: string
  roles: Role[]
  email: string | null
}

const seed = ref<DemoAccount[]>([])
const staff = ref<StaffAccount[]>([])
const jobs = ref<NotificationJob[]>([])
const template = ref<NotificationTemplate>('NIGHT_ROSTER')
const picked = ref<string[]>([])
const students = ref('')
const deliverNow = ref(true)
const busy = ref<string | null>(null)
const loading = ref(true)
const notice = ref<{ text: string; bad: boolean } | null>(null)

const candidates = computed<Recipient[]>(() => {
  const unified = seed.value
    .filter((item) => item.roles.some((role) => TEMPLATE_ROLES[template.value].includes(role)))
    .map((item) => ({
      id: item.user_id,
      label: item.display_name,
      roles: item.roles,
      email: item.email ?? null,
    }))
  const local = TEMPLATE_ROLES[template.value].includes('DORM_MANAGER')
    ? staff.value
        .filter((item) => item.status === 'ACTIVE')
        .map((item) => ({
          id: item.id,
          label: `${item.display_name}（工号 ${item.login_name}）`,
          roles: ['DORM_MANAGER' as Role],
          email: null,
        }))
    : []
  return [...unified, ...local]
})

watch(template, () => {
  const legal = new Set(candidates.value.map((item) => item.id))
  picked.value = picked.value.filter((id) => legal.has(id))
})

const canSubmit = computed(() => picked.value.length > 0 && busy.value === null)

async function load() {
  loading.value = true
  notice.value = null
  try {
    const [accounts, jobsPage, staffPage] = await Promise.all([
      api.demoAccounts(),
      api.notificationJobs(),
      api.staffAccounts(),
    ])
    seed.value = accounts
    jobs.value = jobsPage.items
    staff.value = staffPage.items
  } catch (cause) {
    notice.value = { text: describeError(cause), bad: true }
  } finally {
    loading.value = false
  }
}

async function dispatch() {
  busy.value = 'dispatch'
  notice.value = null
  try {
    const result = await api.dispatchNotifications({
      template: template.value,
      recipient_user_ids: picked.value,
      student_ids: students.value
        .split(/[,，\s]+/)
        .map((value) => value.trim())
        .filter(Boolean),
      deliver_now: deliverNow.value,
    })
    const job = result.jobs[0]
    notice.value = {
      text: result.deduped
        ? `同一任务已在队列中，未重复入队：${job.business_key}`
        : `已入队 ${job.business_key}，${deliverNow.value ? 'worker 下一轮消费' : `计划 ${job.planned_at.slice(5, 16)}`}`,
      bad: false,
    }
    jobs.value = (await api.notificationJobs()).items
  } catch (cause) {
    notice.value = { text: describeError(cause), bad: true }
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
        <h2>演示投递</h2>
        <button class="panel__reload" type="button" @click="load">刷新</button>
      </div>

      <p v-if="notice" class="resv__notice" :class="{ 'resv__notice--bad': notice.bad }">{{ notice.text }}</p>

      <form class="resv__form" @submit.prevent="dispatch">
        <label class="resv__field">
          <span class="resv__label">模板</span>
          <select v-model="template">
            <option v-for="(label, key) in TEMPLATE_LABELS" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>
        <label class="resv__field resv__field--wide">
          <span class="resv__label">正文取数学生（留空为全部）</span>
          <input v-model="students" placeholder="stu_synth_0001" />
        </label>
        <fieldset class="notify__recipients">
          <legend>收件人</legend>
          <label v-for="item in candidates" :key="item.id" class="notify__recipient">
            <input v-model="picked" type="checkbox" :value="item.id" />
            <span>{{ item.label }}</span>
            <span class="notify__channel">{{ item.email ?? '站内待办' }}</span>
          </label>
          <p v-if="!candidates.length" class="panel__placeholder">该模板没有可选收件人。</p>
        </fieldset>
        <label class="notify__toggle">
          <input v-model="deliverNow" type="checkbox" />
          <span>立即由 worker 消费</span>
        </label>
        <div class="resv__actions">
          <button class="resv__primary" type="submit" :disabled="!canSubmit">
            {{ busy === 'dispatch' ? '入队中' : '生成任务' }}
          </button>
        </div>
      </form>
    </section>

    <section class="panel">
      <div class="panel__head">
        <h2>后台任务</h2>
      </div>
      <ul v-if="jobs.length" class="notify__jobs">
        <li v-for="job in jobs" :key="job.id" class="notify__job">
          <span class="notify__status" :class="`notify__status--${job.status.toLowerCase()}`">
            {{ STATUS_LABELS[job.status] ?? job.status }}
          </span>
          <span class="notify__jobmain">{{ job.template }} · {{ job.service_date }} · 收件人 {{ job.recipient_user_ids.length }}</span>
          <span class="notify__key">{{ job.business_key }}</span>
          <span class="notify__meta">计划 {{ job.planned_at.slice(5, 16) }} · 第 {{ job.attempts }} 次</span>
          <span v-if="job.last_error" class="notify__error">{{ job.last_error }}</span>
        </li>
      </ul>
      <p v-else-if="loading" class="panel__placeholder">读取任务表中……</p>
      <p v-else class="panel__placeholder">任务表为空。</p>
    </section>
  </div>
</template>

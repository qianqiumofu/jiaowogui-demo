<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from '@/shared/api/client'
import type { Notification, NotificationTemplate } from '@/shared/api/types'
import { describeError, useSessionStore } from '@/shared/stores/session'

const TEMPLATE_LABELS: Record<NotificationTemplate, string> = {
  NIGHT_ROSTER: '24:00 名单',
  DORM_APPROVED: '预约通过',
  DORM_RESCHEDULED: '预约改期',
  DORM_CANCELLED: '预约撤销',
  DAILY_REPORT: '日报',
  WEEKLY_REPORT: '周报',
  RISK_ALERT: '跟进提示',
}

const session = useSessionStore()
const items = ref<Notification[]>([])
const loading = ref(true)
const busy = ref<string | null>(null)
const opened = ref<string | null>(null)
const notice = ref<{ text: string; bad: boolean } | null>(null)

const unread = computed(() => items.value.filter((item) => item.status === 'SENT').length)

function templateLabel(template: NotificationTemplate): string {
  return TEMPLATE_LABELS[template] ?? template
}

function moment(iso: string): string {
  return `${iso.slice(5, 10)} ${iso.slice(11, 16)}`
}

async function load() {
  loading.value = true
  try {
    items.value = (await api.inbox()).items
  } catch (cause) {
    notice.value = { text: describeError(cause), bad: true }
  } finally {
    loading.value = false
  }
}

async function toggle(item: Notification) {
  opened.value = opened.value === item.id ? null : item.id
  if (item.status === 'SENT' && opened.value === item.id && session.can('notification:mark_read')) {
    busy.value = item.id
    try {
      const read = await api.markNotificationRead(item.id)
      Object.assign(item, read)
    } catch (cause) {
      notice.value = { text: describeError(cause), bad: true }
    } finally {
      busy.value = null
    }
  }
}

onMounted(load)
</script>

<template>
  <section class="panel">
    <div class="panel__head">
      <h2>模拟收件箱</h2>
      <button class="panel__reload" type="button" @click="load">刷新</button>
    </div>
    <p class="panel__line">
      {{ unread ? `${unread} 条未读。` : '没有未读条目。' }}
    </p>

    <p v-if="notice" class="resv__notice" :class="{ 'resv__notice--bad': notice.bad }">{{ notice.text }}</p>

    <ul v-if="items.length" class="inbox__list">
      <li v-for="item in items" :key="item.id" class="inbox__item" :class="{ 'inbox__item--open': opened === item.id }">
        <button class="inbox__head" type="button" @click="toggle(item)">
          <span class="inbox__dot" :class="{ 'inbox__dot--new': item.status === 'SENT' }"></span>
          <span class="inbox__subject">{{ item.subject }}</span>
          <span class="inbox__tag">{{ templateLabel(item.template) }}</span>
          <span class="inbox__tag inbox__tag--channel">{{ item.channel === 'EMAIL' ? '邮件预览' : '站内待办' }}</span>
          <span class="inbox__time">{{ moment(item.created_at) }}</span>
        </button>
        <div v-if="opened === item.id" class="inbox__body">
          <p class="inbox__meta">
            收件地址 {{ item.recipient_email ?? '站内待办，无邮箱' }} · 投递于 {{ moment(item.created_at) }}
            <template v-if="item.read_at"> · 已读于 {{ item.read_at.slice(11, 16) }}</template>
            <template v-if="busy === item.id"> · 更新中</template>
          </p>
          <pre class="inbox__text">{{ item.body }}</pre>
        </div>
      </li>
    </ul>
    <p v-else-if="loading" class="panel__placeholder">读取收件箱中……</p>
    <p v-else class="panel__placeholder">还没有投递给当前账号的通知。</p>
  </section>
</template>

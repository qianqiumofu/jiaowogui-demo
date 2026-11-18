<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { ApiRequestError } from '@/shared/api/client'
import type { ListResult } from '@/shared/api/types'

const props = defineProps<{
  title: string
  loader: () => Promise<ListResult<unknown>>
  owner: 'A' | 'B'
  stage: string
  milestone: string
}>()

type State = { kind: 'loading' } | { kind: 'empty' } | { kind: 'data'; items: unknown[] } | { kind: 'pending'; code: string; message: string } | { kind: 'denied'; code: string; message: string } | { kind: 'error'; code: string; message: string; requestId: string }

const state = ref<State>({ kind: 'loading' })

async function load() {
  state.value = { kind: 'loading' }
  try {
    const result = await props.loader()
    state.value = result.items.length ? { kind: 'data', items: result.items } : { kind: 'empty' }
  } catch (cause) {
    if (cause instanceof ApiRequestError) {
      if (cause.code === 'NOT_IMPLEMENTED') state.value = { kind: 'pending', code: cause.code, message: cause.message }
      else if (cause.code.startsWith('FORBIDDEN') || cause.code === 'SCOPE_UNRESOLVED' || cause.code === 'OUT_OF_SCOPE')
        state.value = { kind: 'denied', code: cause.code, message: cause.message }
      else state.value = { kind: 'error', code: cause.code, message: cause.message, requestId: cause.requestId }
    } else {
      state.value = { kind: 'error', code: 'UNKNOWN', message: String(cause), requestId: '' }
    }
  }
}

const pendingText = computed(() =>
  state.value.kind === 'pending' ? `${props.owner} 负责，${props.milestone} 实现` : '',
)

onMounted(load)
defineExpose({ reload: load })
</script>

<template>
  <section class="panel">
    <header class="panel__head">
      <h2>{{ title }}</h2>
      <button class="panel__reload" type="button" @click="load">重新读取</button>
    </header>

    <p v-if="state.kind === 'loading'" class="panel__line">读取中……</p>

    <div v-else-if="state.kind === 'empty'" class="panel__placeholder">
      <p class="panel__placeholderTitle">{{ title }}：当前没有记录。</p>
      <p class="panel__placeholderNote">接口按契约返回空列表。</p>
    </div>

    <div v-else-if="state.kind === 'pending'" class="panel__placeholder">
      <p class="panel__placeholderTitle">该能力尚未实现。</p>
      <p class="panel__placeholderNote">{{ pendingText }}，阶段 {{ stage }}。</p>
    </div>

    <div v-else-if="state.kind === 'denied'" class="panel__placeholder panel__placeholder--denied">
      <p class="panel__placeholderTitle">后端已拒绝此操作。</p>
      <p class="panel__placeholderNote">{{ state.code }}：{{ state.message }}</p>
    </div>

    <div v-else-if="state.kind === 'error'" class="panel__placeholder panel__placeholder--error">
      <p class="panel__placeholderTitle">{{ state.code }}</p>
      <p class="panel__placeholderNote">{{ state.message }}</p>
      <p v-if="state.requestId" class="panel__requestId">request_id：{{ state.requestId }}</p>
    </div>

    <ul v-else class="panel__list">
      <li v-for="(item, index) in state.items" :key="index">{{ item }}</li>
    </ul>

    <p class="panel__stage">契约阶段：{{ stage }}</p>
  </section>
</template>

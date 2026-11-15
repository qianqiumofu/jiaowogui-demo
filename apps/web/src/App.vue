<script setup lang="ts">
import { RouterView } from 'vue-router'

import { useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()
</script>

<template>
  <div class="appRoot">
    <RouterView />
    <p v-if="!session.ready" class="banner">正在恢复上次会话……</p>
    <p v-else-if="session.error" class="banner banner--error">
      <span>{{ session.error }}</span>
      <button class="banner__close" type="button" @click="session.clearError()">知道了</button>
    </p>
  </div>
</template>

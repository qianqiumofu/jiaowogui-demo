<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { navigationFor } from '@/features/shared/navigation'
import { useSessionStore } from '@/shared/stores/session'

const session = useSessionStore()
const route = useRoute()
const items = computed(() => navigationFor(session.activeRole, session.allowedActions))
const groups = computed(() => [...new Set(items.value.map(item => item.group))])
</script>

<template>
  <nav class="sidenav" aria-label="功能导航">
    <section v-for="group in groups" :key="group" class="sidenav__group">
    <p class="sidenav__groupLabel">{{ group }}</p>
    <RouterLink
      v-for="item in items.filter(item => item.group === group)"
      :key="item.to"
      :to="item.to"
      class="sidenav__item"
      :class="{ 'sidenav__item--active': route.name === item.name }"
    >
      <span>{{ item.label }}</span>
      <em v-if="item.stage" class="sidenav__stage">{{ item.stage }}</em>
    </RouterLink>
    </section>
  </nav>
</template>

<script setup lang="ts">
const props = defineProps<{
  title: string
  owner: 'A' | 'B'
  milestone: string
  note: string
}>()
</script>

<template>
  <section class="stub">
    <div class="stub__head">
      <h2>{{ props.title }}</h2>
      <button class="stub__reload" type="button" disabled>待实现</button>
    </div>
    <p class="stub__title">该能力尚未实现。</p>
    <p class="stub__note">{{ props.note }}</p>
    <p class="stub__meta">负责人 {{ props.owner }} · 阶段 {{ props.milestone }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ modelValue: string; label: string; placeholder: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const shownDate = computed(() => props.modelValue.replace(/^(\d{4})-(\d{2})-(\d{2})$/, '$1年$2月$3日'))
function change(event: Event) { emit('update:modelValue', (event.target as HTMLInputElement).value) }
function openCalendar(event: MouseEvent) { (event.currentTarget as HTMLInputElement).showPicker?.() }
</script>

<template>
  <div class="stat__field">
    <span>{{ label }}</span>
    <div class="date-row">
      <div class="date-control">
        <span class="date-text" :class="{ 'date-empty': !modelValue }">{{ modelValue ? shownDate : placeholder }}</span>
        <svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17"><path d="M7 3v4m10-4v4M4 10h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Z" /></svg>
        <input class="date-input" type="date" :aria-label="label" :value="modelValue" @input="change" @click="openCalendar">
      </div>
      <button v-if="modelValue" type="button" class="date-clear" :aria-label="`清除${label}`" @click="emit('update:modelValue', '')">清除</button>
    </div>
  </div>
</template>

<style scoped>
.date-row { display: flex; gap: 6px; align-items: stretch; }
.date-control { position: relative; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex: 1; min-width: 0; padding: 9px 11px; border: 1px solid var(--line); border-radius: 10px; background: var(--bg-raise); color: var(--ink); }
.date-control:focus-within { outline: 2px solid var(--accent); outline-offset: 2px; }
.date-text { white-space: nowrap; font-variant-numeric: tabular-nums; }
.date-empty { color: var(--ink-dim); }
svg { flex-shrink: 0; fill: none; stroke: var(--ink-dim); stroke-width: 1.6; }
.date-input { position: absolute; inset: 0; width: 100%; height: 100%; min-width: 0; opacity: 0; cursor: pointer; }
.date-clear { padding: 6px 8px; font-size: inherit; color: var(--ink-dim); }
</style>

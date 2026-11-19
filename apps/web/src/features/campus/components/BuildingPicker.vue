<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { StatisticsFilters } from '@/shared/api/types'

type Park = StatisticsFilters['parks'][number]
type Building = StatisticsFilters['buildings'][number]

const props = defineProps<{
  modelValue: string[]
  parks: Park[]
  buildings: Building[]
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [string[]] }>()

const selected = computed(() => props.modelValue)
const parkId = ref('')

// 宿舍区目录异步到达后只初始化一次默认值：优先落到已选楼栋所属宿舍区，避免后续勾选把视图跳走。
watch(
  () => props.parks.length,
  (count) => {
    if (!count || parkId.value) return
    const firstSelected = props.buildings.find((b) => b.building_id === selected.value[0])
    parkId.value = firstSelected?.park_org_id ?? props.parks[0].org_id
  },
  { immediate: true },
)

const parkBuildings = computed(() => props.buildings.filter((b) => b.park_org_id === parkId.value))
const buildingName = (id: string) => props.buildings.find((b) => b.building_id === id)?.name ?? id

function toggle(id: string, on: boolean) {
  emit('update:modelValue', on ? [...new Set([...selected.value, id])] : selected.value.filter((v) => v !== id))
}
function remove(id: string) {
  emit('update:modelValue', selected.value.filter((v) => v !== id))
}
function addPark() {
  emit('update:modelValue', [...new Set([...selected.value, ...parkBuildings.value.map((b) => b.building_id)])])
}
</script>

<template>
  <div class="bpicker">
    <label class="bpicker__park">
      <span class="bpicker__label">宿舍区</span>
      <select v-model="parkId" :disabled="disabled">
        <option v-for="p in parks" :key="p.org_id" :value="p.org_id">{{ p.name }}（{{ p.building_count }} 栋）</option>
      </select>
    </label>
    <div class="bpicker__list">
      <label v-for="b in parkBuildings" :key="b.building_id" class="bpicker__item">
        <input
          type="checkbox"
          :checked="selected.includes(b.building_id)"
          :disabled="disabled"
          @change="toggle(b.building_id, ($event.target as HTMLInputElement).checked)"
        />
        {{ b.name }} · {{ b.code }}
      </label>
      <p v-if="!parkBuildings.length" class="bpicker__empty">该宿舍区下没有楼栋。</p>
    </div>
    <div class="bpicker__actions">
      <strong>已选 {{ selected.length }} 栋</strong>
      <button type="button" :disabled="disabled || !parkBuildings.length" @click="addPark">加入本宿舍区全部</button>
    </div>
    <div class="bpicker__chips">
      <button
        v-for="id in selected"
        :key="id"
        type="button"
        class="bpicker__chip"
        :disabled="disabled"
        :aria-label="`移除${buildingName(id)}`"
        @click="remove(id)"
      >
        {{ buildingName(id) }} ×
      </button>
      <span v-if="!selected.length" class="bpicker__none">尚未选择楼栋</span>
    </div>
  </div>
</template>

<style scoped>
.bpicker { display: flex; flex-direction: column; gap: 10px; }
.bpicker__park { display: flex; flex-direction: column; gap: 6px; }
.bpicker__label { color: var(--ink-faint); font-size: 12.5px; }
.bpicker__list {
  display: grid;
  gap: 8px;
  max-height: 240px;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
}
.bpicker__item { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
.bpicker__empty, .bpicker__none { color: var(--ink-faint); font-size: 12.5px; }
.bpicker__actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.bpicker__actions button {
  background: var(--accent-soft);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 7px 12px;
}
.bpicker__actions button:disabled { opacity: .45; cursor: not-allowed; }
.bpicker__chips { display: flex; flex-wrap: wrap; gap: 6px; }
.bpicker__chip {
  padding: 3px 10px;
  border: 1px dashed var(--line);
  border-radius: 8px;
  background: transparent;
  color: var(--ink-dim);
  font-size: 12px;
}
.bpicker__chip:disabled { opacity: .45; cursor: not-allowed; }
</style>

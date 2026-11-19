<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/shared/api/client'
import type { DutyAssignment, StaffAccount } from '@/shared/api/types'
import { describeError } from '@/shared/stores/session'
const rows=ref<DutyAssignment[]>([]), staff=ref<StaffAccount[]>([]), buildings=ref<Array<{building_id?:string,name:string}>>([])
const selected=ref(''), building=ref(''), start=ref(''), end=ref(''), zone=ref('+08:00'), message=ref('')
async function load(){try{const [d,s,o,c]=await Promise.all([api.duties(),api.staffAccounts(),api.statisticsFilters(),api.clock()]);rows.value=d.items;staff.value=s.items.filter(x=>x.status==='ACTIVE');buildings.value=o.buildings;selected.value ||= staff.value[0]?.id??'';building.value ||= buildings.value[0]?.building_id??'';zone.value=c.now.slice(-6)}catch(e){message.value=describeError(e)}}
async function assign(){try{await api.assignDuty({staff_user_id:selected.value,building_id:building.value,shift_start:start.value+':00'+zone.value,shift_end:end.value+':00'+zone.value});message.value='指派已保存，到生效时刻后后端自动授权。';await load()}catch(e){message.value=describeError(e)}}
async function revoke(id:string){try{await api.revokeDuty(id);message.value='指派已撤销，历史区间保留。';await load()}catch(e){message.value=describeError(e)}}
onMounted(load)
</script>
<template><div class="stack"><section class="panel"><h2>宿管值班与跨楼栋代班</h2><p>由园区指派。固定管理楼栋继续有效，代班只在服务端判定的时间区间内生效。</p><p v-if="message" role="status">{{ message }}</p><form class="manage-grid" @submit.prevent="assign"><label>宿管<select v-model="selected"><option v-for="s in staff" :key="s.id" :value="s.id">{{ s.display_name }}</option></select></label><label>楼栋<select v-model="building"><option v-for="b in buildings" :key="b.building_id" :value="b.building_id">{{ b.name }}</option></select></label><label>开始（业务时区）<input v-model="start" type="datetime-local" required></label><label>结束（业务时区）<input v-model="end" type="datetime-local" required></label><button type="submit">保存指派</button></form></section><section class="panel"><h2>已登记班次</h2><ul><li v-for="r in rows" :key="r.duty_id">{{ staff.find(s=>s.id===r.staff_user_id)?.display_name??r.staff_user_id }} · {{ r.building_id }} · {{ r.shift_start }} — {{ r.shift_end }} <button @click="revoke(r.duty_id)">撤销</button></li></ul></section></div></template>

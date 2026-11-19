<script setup lang="ts">
import { computed } from 'vue'
import { recentTrend } from '../statisticsTrend'
const props = defineProps<{ days: Array<{ service_date: string; nights: number }>; range: { date_from: string; date_to: string } }>()
const trend = computed(() => recentTrend(props.days, props.range))
</script>
<template><p class="panel__line"><template v-if="trend">近 7 夜晚归 {{ trend.recent }} 夜，前 7 夜 {{ trend.prior }} 夜：{{ trend.delta === 0 ? '持平' : `${trend.delta > 0 ? '增加' : '减少'} ${Math.abs(trend.delta)} 夜` }}<template v-if="trend.percent !== null">（{{ trend.percent > 0 ? '+' : '' }}{{ trend.percent }}%）</template><template v-else>；前期为 0，不计算百分比</template>。数值截至本次查询；区间包含当前业务夜时，该夜仍在进行中。</template><template v-else>所选区间不足连续 14 夜，不给出近 7 夜与前 7 夜的变化结论。</template></p></template>

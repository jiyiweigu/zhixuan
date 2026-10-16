<script setup lang="ts">
import { computed } from 'vue'
// 契约 4：confidence 为 0~1 数值、confidence_level 为三档结果；徽标直接用后端判定，前端不另设阈值。
const props = defineProps<{ level: 'high' | 'medium' | 'low'; score?: number }>()
const label = { high: '高置信度', medium: '中置信度', low: '低置信度' }
const pct = computed(() =>
  typeof props.score === 'number' ? Math.round(Math.min(1, Math.max(0, props.score)) * 100) : null,
)
</script>
<template>
  <span class="confidence" :class="`confidence-${level}`">
    <span>{{ label[level] }}</span>
    <small v-if="pct !== null">{{ pct }}%</small>
    <span v-if="pct !== null" class="confidence-bar" aria-hidden="true"><i :style="{ width: `${pct}%` }" /></span>
    <small v-if="level === 'low'">建议人工核实</small>
  </span>
</template>

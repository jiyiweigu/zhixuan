<script setup lang="ts">
const props = defineProps<{tier:'冲'|'稳'|'保';items:Zhixuan.PlanItem[];count?:number}>()
</script>
<template><section class="tier-card"><header><b>{{tier}}</b><span>{{props.count ?? items.length}} 个志愿</span></header><p v-for="item in items" :key="item.order">{{item.order}}. {{item.school_name}}<template v-if="item.group_code"> · 专业组 {{item.group_code}}</template> · {{item.major_names.join('、')}}</p><p v-if="!items.length" class="muted">暂无候选志愿</p></section></template>

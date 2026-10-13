<script setup lang="ts">
defineProps<{ analysis: { label:string; trend:string; disclaimer:string; explanation:string } }>()
</script>
<template><aside class="trend-analysis" :data-trend="analysis.trend"><strong>竞争热度：{{ analysis.label }}</strong><p>{{ analysis.explanation }}</p><small>{{ analysis.disclaimer }}</small></aside></template>
<style scoped>.trend-analysis{border:1px solid #d9d7d2;padding:16px;background:#f9f8f6}.trend-analysis p{margin:8px 0;color:#62605b}.trend-analysis small{color:#8a8882}</style>

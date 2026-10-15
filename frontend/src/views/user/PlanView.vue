<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../../api'
import { useProfileStore } from '../../stores/profile'
import StrategyTabs from '../../components/common/StrategyTabs.vue'
import TierCard from '../../components/common/TierCard.vue'
import CitationList from '../../components/common/CitationList.vue'
const profileStore = useProfileStore()
const strategy = ref<'school'|'major'|'city'>('major')
const data = ref<Zhixuan.Recommendation|null>(null)
const saving = ref(false)
const error = ref('')
// 契约 5：条目在 data.items[]，按 item.tier 分组；tiers 仅为各档数量
const tierKeys: Array<'冲'|'稳'|'保'> = ['冲','稳','保']
const grouped = computed<Record<string, Zhixuan.PlanItem[]>>(() => {
  const g: Record<string, Zhixuan.PlanItem[]> = { 冲: [], 稳: [], 保: [] }
  for (const item of data.value?.items || []) { (g[item.tier] ||= []).push(item) }
  return g
})
function tierCount(tier: string) { return data.value?.tiers?.[tier] ?? grouped.value[tier]?.length ?? 0 }
onMounted(async () => { if (!profileStore.loaded) await profileStore.load() })
async function generate() {
  error.value = ''
  if (!profileStore.profile) await profileStore.load()
  const p = profileStore.profile
  if (!p?.province || p?.score == null) { error.value = '请先完善考生档案中的省份与分数'; return }
  data.value = await api.recommend({ strategy: strategy.value, profile: p, province: p.province, score: p.score })
}
async function save() {
  if (!data.value) return
  saving.value = true
  await api.savePlan({ name: '我的志愿方案', strategy: strategy.value, items: data.value.items || [] })
  saving.value = false
}
</script>
<template><section class="content-page"><div class="eyebrow">PLAN / RECOMMEND</div><h1>我的志愿方案</h1><p class="lede">方案依据你的考生档案生成；修改档案后请重新生成。</p><StrategyTabs v-model="strategy"/><div class="hero-actions"><button class="primary" @click="generate">生成志愿方案 ↗</button><button v-if="data" class="text-btn" :disabled="saving" @click="save">{{saving?'保存中…':'保存方案'}}</button></div><p v-if="error" class="state-box">{{error}}</p><div v-if="data" class="tier-grid"><TierCard v-for="tier in tierKeys" :key="tier" :tier="tier" :count="tierCount(tier)" :items="grouped[tier]"/></div><p v-if="data?.summary" class="muted">{{data.summary}}</p><CitationList v-if="data" :citations="data.citations"/></section></template>

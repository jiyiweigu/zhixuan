<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api'
import { useProfileStore } from '../../stores/profile'
import EligibilityList from '../../components/common/EligibilityList.vue'
import DataStatusTag from '../../components/common/DataStatusTag.vue'
const profile = useProfileStore()
const loading = ref(false)
const result = ref<Zhixuan.EligibilityCheckResp | null>(null)
const error = ref('')
onMounted(() => profile.load())
async function run() {
  loading.value = true; error.value = ''
  try {
    if (!profile.profile) await profile.load()
    const p: any = profile.profile
    if (!p?.province || p?.score == null) { error.value = '请先完善档案中的省份与分数'; return }
    // 契约 8.4：请求体为 { profile, year, items }；本次无具体志愿单位，空 items 合法（summary.total=0）
    result.value = await api.eligibility({
      profile: {
        province: p.province, exam_type: p.exam_type ?? null, first_subject: p.first_subject ?? null,
        second_subjects: p.second_subjects ?? null, score: p.score, rank: p.rank ?? null,
        color_vision: p.color_vision ?? null, vision_left: p.vision_left ?? null, vision_right: p.vision_right ?? null,
        height: p.height ?? null, weight: p.weight ?? null, hepatitis_b: p.hepatitis_b ?? null,
        hearing: p.hearing ?? null, smell: p.smell ?? null, stutter: p.stutter ?? null,
        household_type: p.household_type ?? null, home_county: p.home_county ?? null,
        home_county_code: p.home_county_code ?? null, school_years: p.school_years ?? null,
        tuition_budget: p.tuition_budget ?? null
      },
      year: new Date().getFullYear(),
      items: []
    })
  } catch (e: any) { error.value = e.message || '资格自检暂不可用' } finally { loading.value = false }
}
</script>
<template><section class="content-page"><div class="eyebrow">PATHWAY / CHECK</div><h1>资格自检</h1><p class="lede">自检条件来自你的考生档案；修改档案后请重新检查。</p><button class="primary" :disabled="loading" @click="run">{{loading?'检查中…':'开始自检 ↗'}}</button><p v-if="error" class="state-box">{{error}}</p><template v-if="result"><div class="hero-actions"><DataStatusTag :status="result.data_status"/><span class="muted">共 {{result.summary.total}} 个志愿单位 · 不符合 {{result.summary.blocked}} · 有风险 {{result.summary.warned}} · 待核验 {{result.summary.unknown}}</span></div><EligibilityList :items="result.items"/></template><div v-else-if="!error" class="state-box">填写并保存档案后查看结果。</div></section></template>

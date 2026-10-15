<script setup lang="ts">
// 契约 8.4：条目字段 unit_id / eligible / blockers[] / warnings[] / unknowns[] / citations[]
defineProps<{items: Zhixuan.EligibilityResult[]}>()
const levelText: Record<string, string> = { reject: '不符合', not_suitable: '不宜报考', soft: '有风险', unknown: '待核验' }
function eligibleText(e: boolean | null) { return e === true ? '符合' : e === false ? '不符合' : '待核验' }
</script>
<template><div class="result-list"><article v-for="r in items" :key="r.unit_id" class="result-row"><h3>{{r.unit_id}} <span class="status-tag">{{eligibleText(r.eligible)}}</span></h3><ul v-if="r.blockers?.length"><li v-for="(b,i) in r.blockers" :key="i">{{levelText[b.level] || b.level}}：{{b.detail}}<small v-if="b.major_names?.length">（{{b.major_names.join('、')}}）</small></li></ul><ul v-if="r.warnings?.length"><li v-for="(w,i) in r.warnings" :key="i">{{levelText[w.level] || w.level}}：{{w.detail}}<small v-if="w.major_names?.length">（{{w.major_names.join('、')}}）</small></li></ul><ul v-if="r.unknowns?.length"><li v-for="(u,i) in r.unknowns" :key="i">{{levelText[u.level] || '待核验'}}：{{u.detail}}<small v-if="u.fields?.length">（缺 {{u.fields.join('、')}}）</small></li></ul><details v-if="r.citations?.length"><summary>查看依据来源</summary><p v-for="(c,i) in r.citations" :key="i">{{c.source_name}}（{{c.year}}）</p></details></article><p v-if="!items.length" class="muted">没有可校验的志愿单位。</p></div></template>

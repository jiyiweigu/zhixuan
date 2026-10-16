<script setup lang="ts">
import GateLadder from './GateLadder.vue'
import SourceCard from './SourceCard.vue'
// 契约 8.4：逐单元呈现 { eligible, blockers[], warnings[], unknowns[], citations[] }。
// 铁律：blockers 突出后果、unknowns 不得弱化或折叠、无规则数据时不得显示「通过」。
const props = defineProps<{ items: Zhixuan.EligibilityResult[]; dataStatus?: string }>()
const emit = defineEmits<{ (e: 'go-profile'): void }>()

const typeLabel: Record<string, string> = {
  province_rule: '省份规则', batch: '批次', subject: '选科', language: '语种',
  gender: '性别', score: '分数', pathway: '专项资格', physical: '体检', fee: '学费',
}
// 档案字段 → 人话（unknowns.fields / 补全引导）
const fieldLabel: Record<string, string> = {
  color_vision: '色觉', vision_left: '左眼视力', vision_right: '右眼视力',
  height: '身高', weight: '体重', hepatitis_b: '乙肝表面抗原', hearing: '听力',
  smell: '嗅觉', stutter: '口吃', tuition: '学费数据', tuition_budget: '年学费预算',
  first_subject: '首选科目', second_subjects: '再选科目',
}
const fieldNames = (fields?: string[]) => (fields || []).map((f) => fieldLabel[f] || f)

function verdict(item: Zhixuan.EligibilityResult) {
  if (item.eligible === false) return { text: '不符合', cls: 'bad' }
  if (item.eligible === null) return { text: '待核验', cls: 'warn' }
  return { text: '符合', cls: 'ok' }
}
// 兜底态（任务 T8-B3）：无任何命中 且 规则集未就绪 → 「该目标暂无规则数据」，不做肯定性判断。
function noRuleData(item: Zhixuan.EligibilityResult) {
  const noHits = !(item.blockers?.length || item.warnings?.length || item.unknowns?.length)
  return noHits && props.dataStatus !== 'available' && item.eligible !== false
}
// 后果文案（产品最大价值点）：体检不满足 = 报得上但会被退档；选科不满足 = 报不了。
function consequence(hit: Zhixuan.ConstraintHit): string {
  if (hit.type === 'physical') return '后果提示：体检类不符合「报得上，但会被退档」——志愿能投出去，入校时却因身体条件被退回，是四类不符合中后果最重的一类。'
  if (hit.type === 'subject') return '后果提示：选科不满足属于「报不了」——该志愿单位无法正常投档录取，等于浪费一个志愿位。'
  if (hit.type === 'batch') return '后果提示：批次不匹配属于「报不了」——志愿与当前批次模板不一致，无法投档。'
  return ''
}
</script>
<template>
  <div class="result-list">
    <article v-for="r in items" :key="r.unit_id" class="unit-card">
      <header class="unit-head">
        <div>
          <h3>{{ r.school_name || r.unit_id }}</h3>
          <p class="muted">{{ r.unit_id }}<template v-if="r.group_code"> · 专业组 {{ r.group_code }}</template></p>
        </div>
        <span class="status-tag" :class="`tag-${verdict(r).cls}`">{{ verdict(r).text }}</span>
      </header>

      <GateLadder :blockers="r.blockers" :warnings="r.warnings" :unknowns="r.unknowns" :data-status="dataStatus" />

      <section v-if="r.blockers?.length" class="hit-block hit-block-bad">
        <h4>不符合 · {{ r.blockers.length }} 项 —— 必须处理，否则该志愿无效或退档</h4>
        <ul>
          <li v-for="(b, i) in r.blockers" :key="i" class="hit hit-reject">
            <header><b>{{ typeLabel[b.type] || b.type }}</b><span class="hit-level">不符合</span></header>
            <p class="hit-detail">{{ b.detail }}</p>
            <p v-if="consequence(b)" class="hit-consequence">{{ consequence(b) }}</p>
            <p v-if="b.major_names?.length" class="muted">涉及专业：{{ b.major_names.join('、') }}</p>
            <p v-if="b.citation" class="hit-cite">依据：{{ b.citation.source_name }}（{{ b.citation.year }}）</p>
          </li>
        </ul>
      </section>

      <section v-if="r.warnings?.length" class="hit-block hit-block-warn">
        <h4>风险提示 · {{ r.warnings.length }} 项 —— 可报，但请慎重权衡</h4>
        <ul>
          <li v-for="(w, i) in r.warnings" :key="i" class="hit hit-warn">
            <header><b>{{ typeLabel[w.type] || w.type }}</b><span class="hit-level">有风险</span></header>
            <p class="hit-detail">{{ w.detail }}</p>
            <p v-if="w.major_names?.length" class="muted">涉及专业：{{ w.major_names.join('、') }}</p>
            <p v-if="w.citation" class="hit-cite">依据：{{ w.citation.source_name }}（{{ w.citation.year }}）</p>
          </li>
        </ul>
      </section>

      <section v-if="r.unknowns?.length" class="hit-block hit-block-unknown">
        <h4>待核验 · {{ r.unknowns.length }} 项 —— 未填写 ≠ 合格，补全后重新自检</h4>
        <ul>
          <li v-for="(u, i) in r.unknowns" :key="i" class="hit hit-unknown">
            <header><b>{{ typeLabel[u.type] || u.type }}</b><span class="hit-level">待核验</span></header>
            <p class="hit-detail">{{ u.detail }}</p>
            <p v-if="u.fields?.length" class="hit-fields">缺少档案项：{{ fieldNames(u.fields).join('、') }}
              <button class="text-btn" type="button" @click="emit('go-profile')">去补全 ↗</button>
            </p>
            <p v-if="u.citation" class="hit-cite">依据：{{ u.citation.source_name }}（{{ u.citation.year }}）</p>
          </li>
        </ul>
      </section>

      <section v-if="noRuleData(r)" class="no-rule">
        <b>该目标暂无规则数据</b>
        <p>未匹配到可执行校验的规则集，我们不做肯定性判断——不显示「通过」，也不显示「不符合」。请以官方文件为准，或等待规则数据更新。</p>
      </section>
      <section v-else-if="!r.blockers?.length && !r.warnings?.length && !r.unknowns?.length" class="all-pass">
        四道闸门均未发现问题。结论仍以当年官方政策与高校章程为准。
      </section>

      <details v-if="r.citations?.length" class="unit-cites">
        <summary>该单元依据来源（{{ r.citations.length }}）</summary>
        <SourceCard v-for="(c, i) in r.citations" :key="i" :citation="c" />
      </details>
    </article>
    <p v-if="!items.length" class="state-box">本次没有可校验的目标志愿单位。在上方添加目标（院校专业组）后重新自检。</p>
  </div>
</template>

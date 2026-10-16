<script setup lang="ts">
import { computed } from 'vue'
// 四道闸门（产品书 8.5）：省份规则 → 选科 → 体检 → 学费，串行可视化。
// 状态优先级：拦下(blocker) > 待核验(unknown) > 有风险(warning) > 通过 / 未判定。
// 「未判定」只出现在规则集未就绪（data_status != available）的单元上——与「通过」明确区分，绝不静默放行。
const props = defineProps<{
  blockers?: Zhixuan.ConstraintHit[]
  warnings?: Zhixuan.ConstraintHit[]
  unknowns?: Zhixuan.ConstraintHit[]
  dataStatus?: string
}>()
const GATES: Array<{ key: string; label: string; types: string[] }> = [
  { key: 'province', label: '省份规则', types: ['province_rule', 'batch', 'score', 'pathway'] },
  { key: 'subject', label: '选科', types: ['subject', 'language', 'gender'] },
  { key: 'physical', label: '体检', types: ['physical'] },
  { key: 'fee', label: '学费', types: ['fee'] },
]
type Status = 'blocked' | 'unknown' | 'warned' | 'passed' | 'unjudged'
const steps = computed(() =>
  GATES.map((g) => {
    const has = (list?: Zhixuan.ConstraintHit[]) => (list || []).some((h) => g.types.includes(h.type))
    let status: Status = 'passed'
    let text = '通过'
    if (has(props.blockers)) { status = 'blocked'; text = '拦下' }
    else if (has(props.unknowns)) { status = 'unknown'; text = '待核验' }
    else if (has(props.warnings)) { status = 'warned'; text = '有风险' }
    else if (props.dataStatus && props.dataStatus !== 'available') { status = 'unjudged'; text = '未判定' }
    return { ...g, status, text }
  }),
)
</script>
<template>
  <div class="gate-ladder" role="list" aria-label="四道闸门串行校验">
    <template v-for="(s, i) in steps" :key="s.key">
      <span v-if="i" class="gate-arrow" aria-hidden="true">→</span>
      <div class="gate-node" :class="`gate-${s.status}`" role="listitem">
        <b>{{ s.label }}</b>
        <span>{{ s.text }}</span>
      </div>
    </template>
  </div>
</template>

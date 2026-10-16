<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../../api'
import { useQaStore, type QaMessage } from '../../stores/qa'
import { useAuthStore } from '../../stores/auth'
import CitationList from '../../components/common/CitationList.vue'
import ConfidenceBadge from '../../components/common/ConfidenceBadge.vue'

const qa = useQaStore()
const auth = useAuthStore()
const q = ref('')
const loading = ref(false)
const error = ref('')

// 预设问题：前两条直接演示溯源与空态，第三条演示与自检页的联动。
const presets = [
  '河南 620 分（物理类）能报哪些院校专业？',
  '这个专业今年会涨分吗？',
  '色弱会影响哪些专业报考？',
]

function ask(text?: string) {
  const question = (text ?? q.value).trim()
  error.value = ''
  if (!question) { error.value = '请输入问题（1~500 字）。'; return }
  if (question.length > 500) { error.value = '问题最长 500 字，请精简后再试。'; return }
  q.value = ''
  loading.value = true
  qa.ask(question).finally(() => { loading.value = false })
}

// 联动（任务 T8-A3）：问题或回答涉及「能不能报」类时，给出自检入口。
const CHECK_PATTERN = /(能报|能不能|可报|报哪些|报考|能上|够得着|有资格|适合报|可以报|条件|体检|色弱|色盲|视力)/
function showCheck(m: QaMessage) {
  return CHECK_PATTERN.test(m.question) || CHECK_PATTERN.test(m.result?.answer || '')
}

const historyOpen = ref(false)
const historyLoading = ref(false)
const historyError = ref('')
const history = ref<Zhixuan.QaHistoryItem[]>([])
async function loadHistory() {
  historyOpen.value = true
  if (!auth.isAuthenticated) return
  historyLoading.value = true
  historyError.value = ''
  try {
    const page: any = await api.qaHistory({ page: 1, page_size: 20 })
    history.value = page.items || []
  } catch (e: any) {
    historyError.value = e?.code === 1002 ? '登录状态已失效，请重新登录后查看。' : e?.message || '历史记录加载失败'
  } finally {
    historyLoading.value = false
  }
}
</script>
<template>
  <section class="content-page qa-page">
    <div class="eyebrow">KNOWLEDGE / QA</div>
    <h1>政策问答</h1>
    <p class="lede">每个结论都附带来源、年份与置信度；低置信回答自动进入人工审核队列。有据可查，有疑必审，有缺必说。</p>

    <div class="ask-row">
      <input v-model="q" :disabled="loading" placeholder="例：河南 620 分（物理类）能报哪些院校专业？" @keyup.enter="ask()" />
      <button class="primary" :disabled="loading" @click="ask()">{{ loading ? '检索中…' : '提问 ↗' }}</button>
      <button class="text-btn" type="button" @click="loadHistory">历史记录</button>
    </div>
    <div class="chips">
      <button v-for="p in presets" :key="p" class="chip" type="button" :disabled="loading" @click="ask(p)">{{ p }}</button>
    </div>
    <p v-if="error" class="state-box">{{ error }}</p>

    <section v-if="historyOpen" class="qa-history">
      <header><h3>历史问答</h3><button class="text-btn" type="button" @click="historyOpen = false">收起 ✕</button></header>
      <p v-if="!auth.isAuthenticated" class="state-box">登录后可查看你的历史问答。<RouterLink class="link" to="/login"> 去登录 ↗</RouterLink></p>
      <p v-else-if="historyLoading" class="skeleton">正在加载历史记录…</p>
      <p v-else-if="historyError" class="state-box">{{ historyError }}</p>
      <ul v-else class="history-list">
        <li v-for="h in history" :key="h.qa_log_id">
          <div class="history-head">
            <b>{{ h.question }}</b>
            <ConfidenceBadge :level="['high', 'medium', 'low'].includes(h.confidence) ? (h.confidence as any) : 'low'" />
          </div>
          <p class="muted">{{ h.answer }}</p>
          <p class="muted">{{ (h.created_at || '').slice(0, 16).replace('T', ' ') }}
            <span v-if="h.needs_review" class="status-tag tag-warn">已入审核</span>
          </p>
        </li>
        <li v-if="!history.length" class="muted">暂无历史记录。</li>
      </ul>
    </section>

    <article v-for="m in qa.messages" :key="m.at" class="qa-msg">
      <p class="qa-q">Q · {{ m.question }}</p>

      <div v-if="!m.result && !m.errorCode" class="skeleton">正在检索知识库并核对来源…</div>

      <template v-else-if="m.result">
        <div class="qa-meta">
          <ConfidenceBadge :level="m.result.confidence_level" :score="m.result.confidence" />
          <span class="muted">耗时 {{ m.result.elapsed_ms }} ms</span>
          <span v-if="m.result.degraded" class="status-tag">降级结果（检索片段摘要）</span>
          <span v-if="m.result.needs_review" class="status-tag tag-warn">已入人工审核</span>
        </div>
        <p class="qa-a">{{ m.result.answer }}</p>

        <div v-if="m.result.needs_review" class="review-note">
          该回答可信度较低，已提交人工审核；审核结论将回填知识库并改进后续回答。
        </div>

        <div v-if="!m.result.citations?.length" class="no-evidence">
          <b>知识库暂无该项数据</b>
          <p>没有找到可核验的来源，因此不给出确定性结论——与其猜一个答案，不如坦白说「不知道」。你可以换个问法，或让档案替你回答更具体的问题：</p>
          <div class="hero-actions">
            <RouterLink class="text-btn" to="/profile">完善档案 ↗</RouterLink>
            <RouterLink class="text-btn" to="/eligibility">做资格自检 ↗</RouterLink>
          </div>
        </div>
        <CitationList v-else :citations="m.result.citations" />

        <div v-if="showCheck(m)" class="qa-cta">
          <p>这类问题与你的个人条件强相关——用你的档案跑一次四道闸门，比任何一句话都可靠。</p>
          <RouterLink class="primary" to="/eligibility">去资格自检 ↗</RouterLink>
        </div>
      </template>

      <div v-else class="qa-error">
        <template v-if="m.errorCode === 3001">
          <b>规则数据尚未就绪，无法给出有依据的回答</b>
          <p>{{ m.errorMessage }}</p>
          <p v-if="m.errorData?.missing_rule_sets?.length" class="muted">缺失规则集：{{ m.errorData.missing_rule_sets.join('、') }}</p>
          <p class="muted">当前数据覆盖：河南、江西 · 普通本科批；其余省份正在建设中。</p>
          <div class="hero-actions">
            <RouterLink class="text-btn" to="/pathways">浏览升学途径 ↗</RouterLink>
            <RouterLink class="text-btn" to="/profile">完善档案 ↗</RouterLink>
          </div>
        </template>
        <template v-else>
          <b>提问失败</b>
          <p>{{ m.errorMessage }}<span v-if="m.errorCode === 1001" class="muted">（问题为 1~500 字）</span></p>
          <button class="text-btn" type="button" @click="ask(m.question)">重试 ↻</button>
        </template>
      </div>
    </article>

    <p v-if="qa.messages.length" class="qa-clear"><button class="text-btn" type="button" @click="qa.clear()">清空对话</button></p>
  </section>
</template>

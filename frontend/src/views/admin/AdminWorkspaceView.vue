<script setup lang="ts">
// T7 管理端对齐契约 v1.6：五个 section 的取数一律走契约接口
// （附录 A + §8.8），形状以后端真实 DTO 为准；VITE_USE_MOCK=true 时用同形状 Mock 离线开发。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { api } from '../../api'
import { ApiError } from '../../utils/request'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ section?: string }>()

const rows = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const message = ref('')
const error = ref('')
const loading = ref(false)

const TITLES: Record<string, string> = {
  docs: '语料管理',
  index: '索引管理',
  review: '审核工作台',
  pathways: '途径与规则维护',
  stats: '数据统计',
}
const title = computed(() => TITLES[props.section || ''] || '管理工作台')

// —— 错误文案：3001 / 4001 按契约语义专门提示，绝不静默 ——
function errText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 3001) return '规则数据缺失或未就绪（3001）：该省份/年份/批次的规则尚未导入，相关结论不会臆测放行。请到「途径与规则维护 → 批量导入」补充数据。'
    if (e.code === 4001) return '来源不完整（4001）：事实数据必须携带 source_name / source_url / year 三要素，缺一拒收。'
    if (e.code === 1001) return `参数被拒绝（1001）：${e.message}`
    if (e.code === 1002) return '登录已过期（1002），请重新登录管理端。'
    if (e.code === 1003) return '无权限（1003）：该操作需要管理员角色。'
    return e.message
  }
  return String(e)
}

async function run(fn: () => Promise<void>) {
  error.value = ''
  loading.value = true
  try {
    await fn()
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

const statusLabel = (s: string | undefined | null) =>
  ({ available: '可用', partial: '部分可用', schema_only: '仅结构', unavailable: '不可用', pending: '待审核', approved: '已采纳', corrected: '已修正', rejected: '已驳回', queued: '排队中', running: '执行中', completed: '已完成', failed: '失败' } as Record<string, string>)[s || ''] || s || '—'

// ============================== 语料管理 ==============================
const docFilter = ref({ keyword: '', province: '', year: '', doc_type: '' })
const docForm = ref({ title: '', source_name: '', source_url: '', year: String(new Date().getFullYear()), doc_type: '政策', province: '河南', pathway_id: '', content: '' })
const showDocForm = ref(false)

function loadDocs() {
  return run(async () => {
    const q: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    for (const [k, v] of Object.entries(docFilter.value)) if (String(v).trim()) q[k] = k === 'year' ? Number(v) : v
    const r = await api.adminDocs(q)
    rows.value = r.items
    total.value = r.total
  })
}

function submitDoc() {
  return run(async () => {
    const f = docForm.value
    if (!f.title.trim() || !f.source_name.trim() || !f.source_url.trim() || !Number(f.year)) {
      error.value = '标题与来源三要素（source_name / source_url / year）为必填（缺一后端返回 4001）。'
      return
    }
    await api.uploadDoc({ ...f, year: Number(f.year), pathway_id: f.pathway_id.trim() || null, chunks: f.content ? [f.content] : [] })
    message.value = `语料已导入，来源：${f.source_name}（${f.year}）。切片向化将在「索引管理」增量重建时补齐。`
    showDocForm.value = false
    await loadDocs()
  })
}

function removeDoc(id: number) {
  return run(async () => {
    await api.deleteDoc(id)
    message.value = `语料 #${id} 及其切片已删除（操作已留痕）。`
    await loadDocs()
  })
}

// ============================== 索引管理 ==============================
const rebuildForm = ref({ scope: 'all' as 'all' | 'doc_ids', doc_ids: '', incremental: true })
const taskIdInput = ref('')
const taskState = ref<Zhixuan.IndexTaskState | null>(null)
let pollTimer: ReturnType<typeof setTimeout> | null = null

function rebuild() {
  return run(async () => {
    const docIds = rebuildForm.value.doc_ids.split(/[,，\s]+/).filter(Boolean).map(Number)
    const r = await api.rebuildIndex({ scope: rebuildForm.value.scope, doc_ids: docIds, incremental: rebuildForm.value.incremental })
    message.value = `索引重建任务 #${r.task_id} 已${r.status === 'queued' ? '排队' : '受理'}（后台执行，不阻塞问答）。`
    taskIdInput.value = String(r.task_id)
    await pollTask(r.task_id)
  })
}

function stopPoll() {
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
}

function pollTask(id: number | string) {
  stopPoll()
  return run(async () => {
    taskState.value = await api.indexTask(id)
    const st = taskState.value.status
    if (st === 'queued' || st === 'running') pollTimer = setTimeout(() => pollTask(id), 2000)
  })
}

async function loadIndexSection() {
  stopPoll()
  rows.value = []
  total.value = 0
}

// ============================== 审核工作台 ==============================
const reviewFilter = ref({ status: 'pending', trigger_reason: '' })
const detail = ref<Zhixuan.ReviewTaskItem | null>(null)
const decision = ref({ action: '' as '' | 'approve' | 'correct' | 'reject', corrected_answer: '', comment: '' })

function loadReview() {
  return run(async () => {
    const q: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (reviewFilter.value.status) q.status = reviewFilter.value.status
    if (reviewFilter.value.trigger_reason.trim()) q.trigger_reason = reviewFilter.value.trigger_reason.trim()
    const r = await api.reviewTasks(q)
    rows.value = r.items
    total.value = r.total
  })
}

function openDetail(task: Zhixuan.ReviewTaskItem) {
  return run(async () => {
    detail.value = await api.reviewTask(task.task_id)
    decision.value = { action: '', corrected_answer: '', comment: '' }
    error.value = ''
  })
}

function submitDecision() {
  return run(async () => {
    const t = detail.value
    if (!t) return
    const a = decision.value.action
    if (!a) { error.value = '请先选择审核动作：采纳 / 修改后采纳 / 驳回。'; return }
    if (a === 'correct' && !decision.value.corrected_answer.trim()) { error.value = '「修改后采纳」必须提供修正后的答案（corrected_answer）。'; return }
    await api.reviewAction(t.task_id, { action: a, corrected_answer: decision.value.corrected_answer, comment: decision.value.comment })
    message.value = a === 'approve' ? `任务 #${t.task_id} 已采纳（修正类采纳会把修正内容沉淀回知识库，引用缺来源时不沉淀）。`
      : a === 'correct' ? `任务 #${t.task_id} 已修改并采纳，修正答案沉淀为「审核修正」语料。`
      : `任务 #${t.task_id} 已驳回，原答案不作为结论，留痕可追踪。`
    detail.value = null
    await loadReview()
  })
}

function refreshQueue() {
  return run(async () => {
    const r = await api.reviewEnqueue()
    message.value = `已扫描 ${r.scanned} 条未建单问答，新入队 ${r.enqueued} 条。`
    await loadReview()
  })
}

// ============================== 途径与规则维护 ==============================
const subTab = ref<'pathways' | 'rules' | 'status' | 'import'>('pathways')
const importForm = ref({ dataset: 'subject_requirement', province_code: '41', year: String(new Date().getFullYear()), batch_code: 'undergraduate_regular', exam_type: '普通' })
const importItems = ref<Record<string, unknown>[]>([])
const importFileName = ref('')
const importResult = ref<Zhixuan.RuleImportResult | null>(null)
const DATASETS = ['province_exam_rule', 'subject_requirement', 'physical_restriction', 'admission_requirement', 'major_tuition']

async function loadPathwaySection() {
  if (subTab.value === 'import') { rows.value = []; total.value = 0; return }
  return run(async () => {
    if (subTab.value === 'pathways') {
      rows.value = await api.adminPathways()
      total.value = rows.value.length
    } else if (subTab.value === 'rules') {
      const r = await api.rules()
      rows.value = r.items
      total.value = r.total
    } else {
      const r = await api.ruleDatasetStatus({ page: page.value, page_size: pageSize.value })
      rows.value = r.items
      total.value = r.total
    }
  })
}

function onImportFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  importFileName.value = file.name
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const parsed = JSON.parse(String(reader.result))
      importItems.value = Array.isArray(parsed) ? parsed : [parsed]
      importResult.value = null
      message.value = `已解析 ${file.name}：${importItems.value.length} 条规则项，可提交导入。`
    } catch {
      error.value = '文件不是合法 JSON（需为规则项数组或单个对象）。'
    }
  }
  reader.readAsText(file, 'utf-8')
}

// 粘贴 JSON ⇆ 解析结果的双向代理：粘贴合法 JSON 即填充 items（输入中不报错）
const pastedJson = ref('')
const importItemsJsonProxy = computed<string>({
  get: () => (importItems.value.length ? JSON.stringify(importItems.value, null, 2) : pastedJson.value),
  set: (v: string) => {
    pastedJson.value = v
    try {
      const parsed = JSON.parse(v)
      importItems.value = Array.isArray(parsed) ? parsed : [parsed]
      importResult.value = null
    } catch { /* 输入过程中的中间态，不打断 */ }
  },
})

function precheckItems(): string[] {
  // 行级预检：来源三要素缺失 / 演示来源（后端为最终裁决，整批回滚）
  const problems: string[] = []
  importItems.value.forEach((item, i) => {
    const missing = ['source_name', 'source_url', 'year'].filter(k => !item[k])
    if (missing.length) problems.push(`第 ${i + 1} 行缺来源字段：${missing.join(' / ')}`)
    if (String(item.source_url || '').includes('example.invalid')) problems.push(`第 ${i + 1} 行为演示来源（example.invalid），后端拒收`)
  })
  return problems
}

function submitImport() {
  return run(async () => {
    if (!importItems.value.length) { error.value = '请先选择 JSON 文件或粘贴规则项数组。'; return }
    if (importItems.value.length > 500) { error.value = '契约 8.8：单次导入不得超过 500 条。'; return }
    const pre = precheckItems()
    if (pre.length) { error.value = `行级预检未通过（整批事务，任一行失败会整体回滚）：\n${pre.join('\n')}`; return }
    const r = await api.importRuleDataset({
      dataset: importForm.value.dataset,
      province_code: importForm.value.province_code.trim(),
      year: Number(importForm.value.year),
      batch_code: importForm.value.batch_code.trim(),
      exam_type: importForm.value.exam_type,
      items: importItems.value,
    })
    importResult.value = r
    message.value = `导入完成：${r.dataset} 新建 ${r.created} 条 / 更新 ${r.updated} 条 / 拒收 ${r.rejected} 条。规则集状态已按覆盖率自动重算。`
    await loadPathwaySection()
  })
}

// ============================== 数据统计 ==============================
const stats = ref<Zhixuan.AdminStats | null>(null)
let chart: echarts.ECharts | null = null
const chartEl = ref<HTMLElement | null>(null)

async function loadStats() {
  rows.value = []
  total.value = 0
  return run(async () => {
    stats.value = await api.adminStats()
    await nextTick() // v-if 的图表容器挂载后再初始化 ECharts
    renderChart()
  })
}

function renderChart() {
  const s = stats.value
  if (!s || !chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const names = s.coverage_by_pathway.map(i => i.pathway_name).reverse()
  const docs = s.coverage_by_pathway.map(i => i.doc_count).reverse()
  const chunks = s.coverage_by_pathway.map(i => i.chunk_count).reverse()
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['语料篇数', '切片条数'] },
    grid: { left: 140, right: 24, top: 36, bottom: 24 },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: { type: 'category', data: names },
    series: [
      { name: '语料篇数', type: 'bar', data: docs, itemStyle: { color: '#1c1c1c' } },
      { name: '切片条数', type: 'bar', data: chunks, itemStyle: { color: '#8a8882' } },
    ],
  })
}

// ============================== 装载与切换 ==============================
async function load() {
  message.value = ''
  error.value = ''
  detail.value = null
  importResult.value = null
  page.value = 1
  taskState.value = null
  stopPoll()
  if (props.section === 'docs') await loadDocs()
  else if (props.section === 'index') await loadIndexSection()
  else if (props.section === 'review') await loadReview()
  else if (props.section === 'pathways') await loadPathwaySection()
  else if (props.section === 'stats') await loadStats()
  else { rows.value = []; total.value = 0 }
}

watch(() => props.section, load)
watch(subTab, () => { page.value = 1; loadPathwaySection() })
onMounted(load)
onBeforeUnmount(() => { stopPoll(); chart?.dispose(); chart = null })
</script>

<template>
  <section class="content-page admin-page">
    <div class="eyebrow">ADMIN / {{ (section || '').toUpperCase() }}</div>
    <h1>{{ title }}</h1>
    <p class="lede">管理端操作全部保留来源与留痕。默认走契约 v1.6 真实接口（VITE_USE_MOCK=true 时为同形状离线演示数据）。</p>

    <!-- 语料管理 -->
    <template v-if="section === 'docs'">
      <div class="ask-row">
        <input v-model="docFilter.keyword" placeholder="标题或正文关键词" @keyup.enter="page = 1; loadDocs()" />
        <input v-model="docFilter.province" placeholder="省份，如 河南" style="max-width:140px" @keyup.enter="page = 1; loadDocs()" />
        <input v-model="docFilter.year" placeholder="年份" style="max-width:90px" @keyup.enter="page = 1; loadDocs()" />
        <input v-model="docFilter.doc_type" placeholder="文种，如 章程" style="max-width:130px" @keyup.enter="page = 1; loadDocs()" />
        <button class="primary" @click="page = 1; loadDocs()">筛选 ↗</button>
      </div>
      <div class="hero-actions">
        <button class="primary" @click="showDocForm = !showDocForm">{{ showDocForm ? '收起导入表单' : '导入语料' }} ↗</button>
        <span class="muted">共 {{ total }} 篇 · 缺来源三要素会被 4001 拒收</span>
      </div>
      <form v-if="showDocForm" class="doc-form" @submit.prevent="submitDoc">
        <label>标题 *<input v-model="docForm.title" required /></label>
        <label>来源名称 *<input v-model="docForm.source_name" placeholder="如 河南省教育考试院" required /></label>
        <label>来源 URL *<input v-model="docForm.source_url" placeholder="https://…" required /></label>
        <label>年份 *<input v-model="docForm.year" required /></label>
        <label>文种<input v-model="docForm.doc_type" /></label>
        <label>省份<input v-model="docForm.province" /></label>
        <label>关联途径 ID<input v-model="docForm.pathway_id" placeholder="可空" /></label>
        <label class="span2">正文<textarea v-model="docForm.content" rows="4" /></label>
        <div class="span2"><button class="primary" type="submit">提交导入 ↗</button></div>
      </form>
      <div class="admin-table" v-if="rows.length">
        <div class="table-row table-head"><span>年份</span><span>标题</span><span>来源</span><span>文种 / 省份</span><span>切片</span><span>操作</span></div>
        <div v-for="row in rows" :key="row.doc_id" class="table-row">
          <span>{{ row.year }}</span>
          <span>{{ row.title }}</span>
          <span class="muted">{{ row.source_name }}</span>
          <span>{{ row.doc_type || '—' }} / {{ row.province || '—' }}</span>
          <span>{{ row.chunk_count }}</span>
          <button class="link" @click="removeDoc(row.doc_id)">删除</button>
        </div>
      </div>
    </template>

    <!-- 索引管理 -->
    <template v-else-if="section === 'index'">
      <div class="form-grid index-form">
        <label>范围
          <select v-model="rebuildForm.scope">
            <option value="all">全部切片</option>
            <option value="doc_ids">指定文档</option>
          </select>
        </label>
        <label v-if="rebuildForm.scope === 'doc_ids'">文档 ID（逗号分隔）<input v-model="rebuildForm.doc_ids" placeholder="1,2,3" /></label>
        <label>模式
          <select v-model="rebuildForm.incremental">
            <option :value="true">增量（仅未向量化切片）</option>
            <option :value="false">全量重算</option>
          </select>
        </label>
      </div>
      <div class="hero-actions">
        <button class="primary" @click="rebuild">发起重建 ↗</button>
        <input v-model="taskIdInput" placeholder="任务 ID" style="max-width:120px" />
        <button class="text-btn" @click="taskIdInput && pollTask(taskIdInput)">查询任务状态</button>
      </div>
      <div v-if="taskState" class="state-box index-task">
        <p><b>任务 #{{ taskState.task_id }}</b> · {{ statusLabel(taskState.status) }} · 范围 {{ taskState.scope }}{{ taskState.incremental ? '（增量）' : '（全量）' }}</p>
        <p class="muted">{{ taskState.message || '—' }}</p>
        <div class="progress"><div class="progress-bar" :style="{ width: taskState.progress.percent + '%' }" /></div>
        <p class="muted">进度 {{ taskState.progress.percent }}%：已处理 {{ taskState.progress.processed }}/{{ taskState.progress.total }}，已向量化 {{ taskState.progress.embedded }}，待向量化 {{ taskState.progress.pending_embedding }}，失败 {{ taskState.progress.failed }}<template v-if="!taskState.embedder_ready"> · ⚠️ 向量化服务未注入，任务将以 partial 结束并如实标注</template></p>
      </div>
    </template>

    <!-- 审核工作台 -->
    <template v-else-if="section === 'review'">
      <div class="ask-row">
        <select v-model="reviewFilter.status" @change="page = 1; loadReview()">
          <option value="pending">待审核</option>
          <option value="">全部状态</option>
          <option value="approved">已采纳</option>
          <option value="corrected">已修正</option>
          <option value="rejected">已驳回</option>
        </select>
        <input v-model="reviewFilter.trigger_reason" placeholder="按入队原因过滤，如 低置信" @keyup.enter="page = 1; loadReview()" />
        <button class="primary" @click="page = 1; loadReview()">筛选 ↗</button>
        <button class="text-btn" @click="refreshQueue">刷新待审队列（扫描补建）</button>
      </div>
      <div class="admin-table" v-if="rows.length">
        <div class="table-row table-head"><span>状态</span><span>问题</span><span>入队原因</span><span>置信</span><span>操作</span></div>
        <div v-for="row in rows" :key="row.task_id" class="table-row">
          <span class="data-status">{{ statusLabel(row.status) }}</span>
          <span>{{ row.question }}</span>
          <span class="muted">{{ row.trigger_reason }}</span>
          <span class="muted">{{ row.confidence }}</span>
          <button class="link" @click="openDetail(row)">查看详情</button>
        </div>
      </div>
      <div v-if="detail" class="review-detail">
        <h3>任务 #{{ detail.task_id }} · 问答对照</h3>
        <p><b>问：</b>{{ detail.question }}</p>
        <p><b>原答：</b>{{ detail.original_answer || detail.answer }} <span v-if="detail.degraded" class="muted">（降级回答）</span></p>
        <ul v-if="detail.citations && detail.citations.length" class="muted">
          <li v-for="(c, i) in detail.citations" :key="i">{{ c.source_name }}（{{ c.year }}）<a v-if="c.source_url" :href="c.source_url" target="_blank" rel="noreferrer">原文 ↗</a></li>
        </ul>
        <p v-else class="muted">该问答没有引用原文片段——缺引用的结论按契约不作为定论展示。</p>
        <div class="decision-row">
          <label><input type="radio" value="approve" v-model="decision.action" /> 采纳</label>
          <label><input type="radio" value="correct" v-model="decision.action" /> 修改后采纳</label>
          <label><input type="radio" value="reject" v-model="decision.action" /> 驳回</label>
        </div>
        <label v-if="decision.action === 'correct'" class="correct-box">修正后的答案 *（会沉淀回知识库；引用缺来源三要素时不沉淀）
          <textarea v-model="decision.corrected_answer" rows="3" />
        </label>
        <label>审核备注<input v-model="decision.comment" maxlength="200" placeholder="可空，随留痕保存" /></label>
        <div class="hero-actions">
          <button class="primary" @click="submitDecision">提交决策 ↗</button>
          <button class="text-btn" @click="detail = null">取消</button>
        </div>
      </div>
    </template>

    <!-- 途径与规则维护 -->
    <template v-else-if="section === 'pathways'">
      <div class="strategy-tabs">
        <button :class="{ selected: subTab === 'pathways' }" @click="subTab = 'pathways'">途径字典</button>
        <button :class="{ selected: subTab === 'rules' }" @click="subTab = 'rules'">资格规则</button>
        <button :class="{ selected: subTab === 'status' }" @click="subTab = 'status'">规则集状态</button>
        <button :class="{ selected: subTab === 'import' }" @click="subTab = 'import'">批量导入（§8.8）</button>
      </div>

      <div v-if="subTab === 'pathways'" class="admin-table">
        <div class="table-row table-head"><span>途径</span><span>分类 / 批次</span><span>优先级</span><span>数据状态</span><span>来源</span></div>
        <div v-for="row in rows" :key="row.pathway_id" class="table-row">
          <span>{{ row.name }} <span class="muted">{{ row.pathway_id }}</span></span>
          <span>{{ row.category || '—' }} / {{ row.batch || '—' }}</span>
          <span>{{ row.priority }}</span>
          <span class="data-status">{{ statusLabel(row.data_status) }}</span>
          <span class="muted">{{ row.source?.source_name || '—' }}（{{ row.source?.year || '—' }}）</span>
        </div>
      </div>

      <div v-else-if="subTab === 'rules'" class="admin-table">
        <div class="table-row table-head"><span>途径</span><span>省份</span><span>类型</span><span>规则条文</span><span>来源</span></div>
        <div v-for="row in rows" :key="row.rule_id" class="table-row">
          <span>{{ row.pathway_id }}</span>
          <span>{{ row.province || '通用' }}</span>
          <span>{{ row.rule_type }}</span>
          <span>{{ row.rule_desc || '—' }}</span>
          <span class="muted">{{ row.source?.source_name || '—' }}（{{ row.source?.year || '—' }}）</span>
        </div>
      </div>

      <div v-else-if="subTab === 'status'" class="admin-table">
        <div class="table-row table-head"><span>规则集</span><span>省份 / 年份</span><span>批次 / 考试类型</span><span>状态</span><span>说明</span></div>
        <div v-for="row in rows" :key="row.rule_id" class="table-row">
          <span>{{ row.dataset }}</span>
          <span>{{ row.province_code }} / {{ row.year }}</span>
          <span>{{ row.batch_code || '—' }} / {{ row.exam_type }}</span>
          <span class="data-status">{{ statusLabel(row.status) }}</span>
          <span class="muted">{{ row.note || '—' }}</span>
        </div>
      </div>

      <form v-else class="import-form" @submit.prevent="submitImport">
        <p class="muted">契约 8.8：单次 ≤500 条，整批事务写入——任一项校验失败整批回滚；成功后后端按覆盖率自动重算规则集状态（available 不允许手工设置）。不接受缺来源记录与演示来源（example.invalid）。</p>
        <div class="form-grid">
          <label>数据集 dataset
            <select v-model="importForm.dataset">
              <option v-for="d in DATASETS" :key="d" :value="d">{{ d }}</option>
            </select>
          </label>
          <label>省份代码<input v-model="importForm.province_code" placeholder="41=河南 / 36=江西" /></label>
          <label>年份<input v-model="importForm.year" /></label>
          <label>批次 batch_code<input v-model="importForm.batch_code" placeholder="undergraduate_regular" /></label>
          <label>考试类型
            <select v-model="importForm.exam_type">
              <option>普通</option><option>艺术</option><option>体育</option>
            </select>
          </label>
          <label>规则项 JSON 文件<input type="file" accept=".json,application/json" @change="onImportFile" /></label>
        </div>
        <p class="muted">已选 {{ importFileName || '（未选文件）' }}，解析出 <b>{{ importItems.length }}</b> 条规则项。也可以直接粘贴数组：</p>
        <textarea v-model.lazy="importItemsJsonProxy" rows="5" placeholder='[{ "first_subject": "物理", "secondary_subjects": ["化学"], "logic": "all", "source_name": "…", "source_url": "…", "year": 2026 }]' />
        <div v-if="importItems.length" class="muted precheck">
          <p>行级预检：{{ precheckItems().length ? '存在问题，见下方提示' : '通过（来源三要素齐全，无演示来源）' }}</p>
        </div>
        <div class="hero-actions">
          <button class="primary" type="submit">提交导入 ↗</button>
        </div>
        <div v-if="importResult" class="state-box">
          导入结果：{{ importResult.dataset }} · 新建 {{ importResult.created }} / 更新 {{ importResult.updated }} / 拒收 {{ importResult.rejected }}
          <template v-if="importResult.errors && importResult.errors.length"> · 行级错误：<code>{{ JSON.stringify(importResult.errors) }}</code></template>
        </div>
      </form>
    </template>

    <!-- 数据统计 -->
    <template v-else-if="section === 'stats'">
      <div class="stat-grid" v-if="stats">
        <div class="stat-card"><b>{{ stats.doc_count }}</b><span>语料篇数</span></div>
        <div class="stat-card"><b>{{ stats.chunk_count }}</b><span>切片条数</span></div>
        <div class="stat-card"><b>{{ stats.qa_count }}</b><span>问答总量</span></div>
        <div class="stat-card"><b>{{ stats.low_confidence_count }}</b><span>低置信问答</span></div>
        <div class="stat-card"><b>{{ stats.review_pending_count }}</b><span>待审核任务</span></div>
      </div>
      <p class="muted" v-if="stats">逐途径语料覆盖度（省份粒度列表呈现，不使用地图，规避地图数据合规风险）：</p>
      <div ref="chartEl" class="coverage-chart" v-if="stats && stats.coverage_by_pathway.length" />
      <div class="state-box" v-if="stats && !stats.coverage_by_pathway.length">尚无途径覆盖度数据（pathway 表为空或未关联语料）。</div>
    </template>

    <div v-if="loading" class="state-box">加载中…</div>
    <div v-if="message" class="state-box">{{ message }}</div>
    <div v-if="error" class="state-box error-box">{{ error }}</div>
    <div v-if="!loading && !rows.length && !error && !message && section !== 'index' && section !== 'stats'" class="state-box">
      暂无数据（后端已按契约返回空分页包 {items:[], total:0}）。
    </div>
  </section>
</template>

<style scoped>
.admin-table { border-top: 1px solid var(--line); margin-top: 28px; }
.table-row { display: grid; grid-template-columns: minmax(70px, .7fr) 2.2fr 1.4fr 1.2fr .8fr .8fr; gap: 12px; align-items: baseline; padding: 13px 0; border-bottom: 1px solid var(--line); font-size: 14px; }
.table-row.table-head { color: var(--muted); font-size: 12px; }
.section-tabs .table-row { grid-template-columns: 1.2fr 1fr 1fr 2.4fr 1.2fr; }
.review-detail { border: 1px solid var(--line); padding: 22px; margin-top: 26px; display: grid; gap: 12px; }
.review-detail h3 { margin: 0; font: 400 20px Georgia, serif; }
.decision-row { display: flex; gap: 22px; }
.decision-row label { display: flex; gap: 6px; align-items: center; }
.correct-box textarea, textarea { width: 100%; border: 1px solid var(--line); padding: 10px; font: inherit; margin-top: 6px; }
.doc-form, .import-form { border: 1px solid var(--line); padding: 22px; margin-top: 26px; display: grid; gap: 14px; }
.doc-form { grid-template-columns: repeat(3, 1fr); }
.doc-form label, .import-form label { display: grid; gap: 6px; font-size: 13px; color: var(--muted); }
.doc-form .span2 { grid-column: span 2; }
.doc-form input, .import-form input, .import-form select { border: 1px solid var(--line); padding: 9px 10px; background: transparent; }
.index-form { max-width: 720px; }
.index-form input, .index-form select { border: 1px solid var(--line); padding: 9px 10px; background: transparent; }
.progress { height: 8px; border: 1px solid var(--line); margin: 10px 0; }
.progress-bar { height: 100%; background: #1c1c1c; transition: width .4s; }
.state-box.error-box { border-color: #b3261e; color: #b3261e; white-space: pre-line; }
.stat-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; margin: 34px 0 18px; }
.stat-card { border: 1px solid var(--line); padding: 20px; display: grid; gap: 6px; }
.stat-card b { font: 400 34px Georgia, serif; }
.stat-card span { color: var(--muted); font-size: 13px; }
.coverage-chart { width: 100%; height: 420px; margin-top: 14px; }
.precheck { margin-top: 8px; }
@media (max-width: 860px) {
  .table-row { grid-template-columns: 1fr 1fr; }
  .doc-form { grid-template-columns: 1fr; }
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { api } from '../../api'
import { useProfileStore } from '../../stores/profile'
import { useAuthStore } from '../../stores/auth'
import EligibilityList from '../../components/common/EligibilityList.vue'
import DataStatusTag from '../../components/common/DataStatusTag.vue'

const profileStore = useProfileStore()
const auth = useAuthStore()

// ---- 自检档案（契约 8.2：体检 9 项 + 批次偏好 + 调剂，null = 未填写 ≠ 合格）----
const form = reactive({
  province: '河南',
  exam_type: '普通',
  first_subject: '' as string,
  second_subjects: [] as string[],
  score: null as number | null,
  rank: null as number | null,
  color_vision: null as string | null,
  vision_left: null as number | null,
  vision_right: null as number | null,
  height: null as number | null,
  weight: null as number | null,
  hepatitis_b: null as boolean | null,
  hearing: null as string | null,
  smell: null as string | null,
  stutter: null as string | null,
  tuition_budget: null as number | null,
  batch_preference: ['本科批'] as string[],
  accept_adjustment: null as boolean | null,
})
const SECOND_OPTIONS = ['化学', '生物', '政治', '地理']
const blank = (v: unknown) => v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0)
const num = (v: unknown) => (v === '' || v === null || v === undefined || Number.isNaN(v as number) ? null : v)
const notice = ref('')

function toggleSecond(s: string) {
  const i = form.second_subjects.indexOf(s)
  if (i >= 0) form.second_subjects.splice(i, 1)
  else if (form.second_subjects.length < 2) form.second_subjects.push(s)
  else notice.value = '再选科目最多选择 2 门。'
}

function loadFrom(p: any) {
  if (!p) return
  for (const key of ['province', 'exam_type', 'first_subject', 'second_subjects', 'score', 'rank', 'color_vision', 'vision_left', 'vision_right', 'height', 'weight', 'hepatitis_b', 'hearing', 'smell', 'stutter', 'tuition_budget', 'batch_preference', 'accept_adjustment'] as const) {
    if (p[key] !== undefined && p[key] !== null) (form as any)[key] = p[key]
  }
}
onMounted(async () => {
  if (!auth.isAuthenticated) return
  try { loadFrom(await profileStore.load()) } catch { /* 档案加载失败不阻塞自检 */ }
})

const saving = ref(false)
async function saveProfile() {
  notice.value = ''
  if (!auth.isAuthenticated) { notice.value = '登录后可将档案保存到账号；本页填写的内容在本次自检中同样生效。'; return }
  saving.value = true
  try {
    await profileStore.save(buildProfile())
    notice.value = '档案已保存。未填写项保持为「未填写」。'
  } catch (e: any) {
    notice.value = e?.message || '保存失败，请稍后重试'
  } finally { saving.value = false }
}

function buildProfile() {
  return {
    province: form.province,
    exam_type: form.exam_type,
    // 后端 ConstraintProfile.first_subject 为 str（非可空）：未填写传空串，服务层按未填归一。
    first_subject: form.first_subject || '',
    second_subjects: [...form.second_subjects],
    score: num(form.score),
    rank: num(form.rank),
    color_vision: form.color_vision || null,
    vision_left: num(form.vision_left),
    vision_right: num(form.vision_right),
    height: num(form.height),
    weight: num(form.weight),
    hepatitis_b: form.hepatitis_b,
    hearing: form.hearing || null,
    smell: form.smell || null,
    stutter: form.stutter || null,
    tuition_budget: num(form.tuition_budget),
    batch_preference: [...form.batch_preference],
    accept_adjustment: form.accept_adjustment,
  }
}

// ---- 目标志愿单位（院校专业组；可选）----
const targets = ref<Zhixuan.EligibilityUnit[]>([])
const targetKeyword = ref('')
const targetOptions = ref<any[]>([])
const targetSchool = ref<{ school_id: number | string; name: string } | null>(null)
const targetGroup = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined
function onSearchInput() {
  targetSchool.value = null
  clearTimeout(searchTimer)
  const kw = targetKeyword.value.trim()
  if (!kw) { targetOptions.value = []; return }
  searchTimer = setTimeout(async () => {
    try { const page: any = await api.schools({ keyword: kw, page_size: 8 }); targetOptions.value = page.items || [] }
    catch { targetOptions.value = [] }
  }, 300)
}
function pickSchool(s: any) {
  targetSchool.value = { school_id: s.school_id, name: s.name }
  targetKeyword.value = s.name
  targetOptions.value = []
}
function addTarget() {
  notice.value = ''
  if (!targetSchool.value) { notice.value = '请先从下拉建议中选择院校。'; return }
  const group = targetGroup.value.trim() || '01'
  const unitId = `manual-${targetSchool.value.school_id}-${group}`
  if (targets.value.some((t) => t.unit_id === unitId)) { notice.value = '该目标已在列表中。'; return }
  targets.value.push({ unit_id: unitId, batch: '本科批', school_id: targetSchool.value.school_id, group_code: group, school_name: targetSchool.value.name })
  targetKeyword.value = ''; targetGroup.value = ''; targetSchool.value = null
}
function removeTarget(i: number) { targets.value.splice(i, 1) }

// ---- 运行自检 ----
const loading = ref(false)
const result = ref<Zhixuan.EligibilityCheckResp | null>(null)
const errorCode = ref<number | null>(null)
const errorText = ref('')
const errorData = ref<any>(null)

const datasetLabel: Record<string, string> = {
  province_exam_rule: '省份志愿模式', subject_requirement: '选科要求',
  physical_restriction: '体检限制', major_tuition: '专业学费', pathway_eligibility: '途径资格',
}
const datasetNames = (keys?: string[]) => (keys || []).map((k) => datasetLabel[k] || k)

async function run() {
  notice.value = ''; errorCode.value = null; errorText.value = ''; errorData.value = null
  if (!form.province) { notice.value = '请先选择报考省份。'; return }
  loading.value = true
  try {
    result.value = await api.eligibility({
      profile: buildProfile(),
      items: targets.value.map((t) => ({ unit_id: t.unit_id, batch: t.batch || '本科批', school_id: t.school_id, group_code: t.group_code, major_ids: t.major_ids || [] })),
    })
    await nextTick()
    document.getElementById('verdict')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (e: any) {
    errorCode.value = e?.code ?? 5000
    errorText.value = e?.message || '资格自检暂不可用'
    errorData.value = e?.data ?? null
    result.value = null
  } finally { loading.value = false }
}

const verdict = computed(() => {
  const s = result.value?.summary
  if (!s || !s.total) return { tone: 'none', title: '本次未选择目标志愿单位', text: '已按你的档案检查规则覆盖情况；添加目标（院校专业组）后可得到逐条结论。' }
  if (s.blocked > 0) return { tone: 'bad', title: `存在 ${s.blocked} 个不符合项`, text: '不符合 = 该志愿无法录取或投档后退档，必须处理；逐条后果见下方。' }
  if (s.unknown > 0) return { tone: 'warn', title: `暂无硬性不符合，但有 ${s.unknown} 个目标待核验`, text: '待核验 ≠ 合格：未填写或规则缺失的部分不会被默认放行，补全后可消除。' }
  if (s.warned > 0) return { tone: 'warn', title: `未发现硬性不符合，${s.warned} 个目标存在风险提示`, text: '风险项不改变「可报」结论，但请谨慎权衡。' }
  return { tone: 'ok', title: '未发现不符合或待核验项', text: '结论仍以当年官方政策与高校章程为准。' }
})

function scrollToProfile() {
  document.getElementById('profile-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>
<template>
  <section class="content-page eligibility-page">
    <div class="eyebrow">PATHWAY / CHECK</div>
    <h1>资格自检</h1>
    <p class="lede">每个目标志愿单位都要过四道闸门：省份规则 → 选科 → 体检 → 学费。未填写会按「未知」处理并列出待核验——我们绝不因为「没填」而默认放行。</p>

    <!-- ① 自检档案 -->
    <section id="profile-panel" class="panel">
      <header class="panel-head">
        <h2>① 自检档案</h2>
        <div class="panel-actions">
          <span v-if="profileStore.completeness" class="muted">档案完成度 {{ profileStore.completeness.percent }}%</span>
          <button class="text-btn" type="button" :disabled="saving" @click="saveProfile">{{ saving ? '保存中…' : auth.isAuthenticated ? '保存到我的档案' : '登录后可保存档案' }}</button>
        </div>
      </header>
      <p class="panel-hint">标「未填写」的项将按「未知」处理，<b>不代表合格</b>；体检信息可跳过，但相关专业会显示待核验。</p>

      <div class="form-grid">
        <label>报考省份
          <select v-model="form.province"><option>河南</option><option>江西</option></select>
        </label>
        <label>考试类型
          <select v-model="form.exam_type"><option>普通</option><option>艺术</option><option>体育</option></select>
        </label>
        <label>高考分数 <span v-if="blank(form.score)" class="fill-tag">未填写</span>
          <input v-model.number="form.score" type="number" min="0" max="750" placeholder="如 620" />
        </label>
        <label>省内位次 <span v-if="blank(form.rank)" class="fill-tag">未填写</span>
          <input v-model.number="form.rank" type="number" min="1" placeholder="如 18000" />
        </label>
        <label>首选科目 <span v-if="blank(form.first_subject)" class="fill-tag">未填写</span>
          <select v-model="form.first_subject"><option value="">未填写</option><option>物理</option><option>历史</option></select>
        </label>
        <label>再选科目 <span v-if="blank(form.second_subjects)" class="fill-tag">未填写</span>
          <div class="chips">
            <button v-for="s in SECOND_OPTIONS" :key="s" class="chip" type="button" :class="{ selected: form.second_subjects.includes(s) }" @click="toggleSecond(s)">{{ s }}</button>
          </div>
        </label>
        <label>色觉 <span v-if="blank(form.color_vision)" class="fill-tag">未填写</span>
          <select v-model="form.color_vision">
            <option :value="null">未填写</option><option>正常</option><option>色弱</option><option>色盲</option><option>不能识别红黄绿蓝紫任一色</option>
          </select>
        </label>
        <label>左眼裸眼视力 <span v-if="blank(form.vision_left)" class="fill-tag">未填写</span>
          <input v-model.number="form.vision_left" type="number" step="0.1" min="0" max="10" placeholder="如 4.6" />
        </label>
        <label>右眼裸眼视力 <span v-if="blank(form.vision_right)" class="fill-tag">未填写</span>
          <input v-model.number="form.vision_right" type="number" step="0.1" min="0" max="10" placeholder="如 4.6" />
        </label>
        <label>身高（cm） <span v-if="blank(form.height)" class="fill-tag">未填写</span>
          <input v-model.number="form.height" type="number" min="0" placeholder="如 178" />
        </label>
        <label>体重（kg） <span v-if="blank(form.weight)" class="fill-tag">未填写</span>
          <input v-model.number="form.weight" type="number" min="0" placeholder="如 65" />
        </label>
        <label>乙肝表面抗原携带 <span v-if="blank(form.hepatitis_b) && form.hepatitis_b !== false" class="fill-tag">未填写</span>
          <select v-model="form.hepatitis_b"><option :value="null">未填写</option><option :value="false">不携带</option><option :value="true">携带</option></select>
        </label>
        <label>听力 <span v-if="blank(form.hearing)" class="fill-tag">未填写</span>
          <select v-model="form.hearing"><option :value="null">未填写</option><option>正常</option><option>异常</option></select>
        </label>
        <label>嗅觉 <span v-if="blank(form.smell)" class="fill-tag">未填写</span>
          <select v-model="form.smell"><option :value="null">未填写</option><option>正常</option><option>异常</option></select>
        </label>
        <label>口吃 <span v-if="blank(form.stutter)" class="fill-tag">未填写</span>
          <select v-model="form.stutter"><option :value="null">未填写</option><option>正常</option><option>异常</option></select>
        </label>
        <label>年学费预算（元） <span v-if="blank(form.tuition_budget)" class="fill-tag">未填写</span>
          <input v-model.number="form.tuition_budget" type="number" min="0" placeholder="如 15000" />
        </label>
        <label>是否服从专业调剂 <span v-if="blank(form.accept_adjustment)" class="fill-tag">未填写</span>
          <select v-model="form.accept_adjustment"><option :value="null">未填写</option><option :value="true">接受</option><option :value="false">不接受</option></select>
        </label>
      </div>
      <p v-if="notice" class="state-box">{{ notice }}</p>
    </section>

    <!-- ② 目标志愿单位 -->
    <section class="panel">
      <header class="panel-head"><h2>② 目标志愿单位（可选）</h2></header>
      <p class="panel-hint">目标 = 「院校专业组」。不添加也可以自检（只检查档案与规则覆盖情况）；演示模式下会展示示例目标。</p>
      <div class="target-add">
        <div class="target-search">
          <input v-model="targetKeyword" placeholder="输入院校名称搜索" @input="onSearchInput" />
          <ul v-if="targetOptions.length" class="target-options">
            <li v-for="s in targetOptions" :key="s.school_id" @click="pickSchool(s)">{{ s.name }} <span class="muted">{{ s.province }}</span></li>
          </ul>
        </div>
        <input v-model="targetGroup" class="target-group" placeholder="专业组编号（如 01）" />
        <button class="text-btn" type="button" @click="addTarget">＋ 添加目标</button>
      </div>
      <ul v-if="targets.length" class="target-list">
        <li v-for="(t, i) in targets" :key="t.unit_id">
          <span>{{ t.school_name }} · 专业组 {{ t.group_code }}</span>
          <button class="text-btn" type="button" @click="removeTarget(i)">移除 ✕</button>
        </li>
      </ul>
    </section>

    <div class="hero-actions">
      <button class="primary" :disabled="loading" @click="run">{{ loading ? '逐条过闸中…' : '开始自检 ↗' }}</button>
      <RouterLink class="text-btn" to="/qa">看不懂术语？去政策问答 ↗</RouterLink>
    </div>

    <!-- 3001：规则未就绪（不得回退为“通过”） -->
    <div v-if="errorCode === 3001" class="state-box err-special">
      <b>报考规则数据尚未就绪，无法完成校验</b>
      <p>{{ errorText }}</p>
      <p v-if="errorData?.missing_rule_sets?.length" class="muted">缺失规则集：{{ datasetNames(errorData.missing_rule_sets).join('、') }}</p>
      <p class="muted">当前数据覆盖：河南、江西 · 普通本科批。规则补齐后本页会自动可用。</p>
    </div>
    <p v-else-if="errorText" class="state-box">{{ errorText }}</p>

    <!-- 汇总结论（置顶） -->
    <template v-if="result">
      <section id="verdict" class="verdict" :class="`verdict-${verdict.tone}`">
        <div class="verdict-head">
          <h2>{{ verdict.title }}</h2>
          <DataStatusTag :status="result.data_status" />
        </div>
        <p>{{ verdict.text }}</p>
        <p class="muted">
          共 {{ result.summary.total }} 个目标 · 不符合 {{ result.summary.blocked }} · 有风险 {{ result.summary.warned }} · 待核验 {{ result.summary.unknown }}
          <template v-if="result.missing_rule_sets?.length"> · 尚未就绪的规则集：{{ datasetNames(result.missing_rule_sets).join('、') }}</template>
        </p>
      </section>
      <EligibilityList :items="result.items" :data-status="result.data_status" @go-profile="scrollToProfile" />
    </template>
    <div v-else-if="!errorText" class="state-box">填写档案、添加目标后点击「开始自检」。每一次判断都会附带依据；待核验项永不隐藏。</div>
  </section>
</template>

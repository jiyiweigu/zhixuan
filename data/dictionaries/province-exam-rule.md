# 省份志愿模式规则数据说明（`province_exam_rule`）

> 产出人：徐（③ 数据工程） ｜ 版本：v1.0 ｜ 日期：2026-10-12
> 数据文件：`data/dictionaries/province-exam-rule.json`
> 校验脚本：`data/scripts/validate_exam_rule.py`（+ `validate.py --kind province_exam_rule`）
> 依据文档：《数据源与数据获取方案》§4.3 ｜《开发产品书》第 7 章 `province_exam_rule`
> 对应任务卡：`docs/执行计划_报考约束接入.md` → ③ 数据 →「河南 2026 本科批 48 组模板 / 江西 2026 本科批 45 组模板（附官方来源）」

---

## 一、这份数据解决什么问题

方案生成器（② 的 `plan_builder.py`）必须**按省 × 批次模板渲染志愿表**：
河南本科批输出「48 行 ×（1 个院校专业组 + 6 个专业 + 是否调剂）」，江西输出「45 行 …」。
模板不同，导出格式就不同。本文件就是这套模板的**唯一事实来源**。

同时资格引擎也要用它判断：志愿数上限、是否需要调剂、提前批各类能否兼报。

---

## 二、本期范围（如实标注）

| 层级 | 省份 | 年份 | 批次 | 状态 |
|---|---|---|---|---|
| **P0 做真** | 河南 | 2026 | 普通本科批 | ✅ `verified` |
| **P0 做真** | 江西 | 2026 | 本科批次 | ✅ `verified` |
| 登记备查 | 河南 | 2026 | 普通本科提前批 / 高职（专科）批 | ✅ `verified`（数值已核实，产品 P2 暂不支持渲染） |
| 登记备查 | 江西 | 2026 | 高职（专科）批次 / 艺术体育本科批 | ✅ `verified`（同上） |
| 骨架 | 河南 | 2024 | 本科一批（老高考） | ⚠️ `schema_only`，**数值未经核实，不得使用** |

**未做**：其他 29 省、2022–2025 各年规则、专业级选科要求细则 —— 均为后续任务，**不在此文件内编造**。

---

## 三、核心口径（均逐字来自官方一手源）

### 3.1 河南 2026 · 普通本科批

| 字段 | 值 | 官方原文依据 |
|---|---|---|
| `mode` | `group`（院校专业组） | — |
| `volunteer_count` | **48** | 「设置48个院校专业组志愿」 |
| `majors_per_group` | **6** | 「内设6个专业志愿及是否同意专业调剂选项」 |
| `has_adjust` | **true** | 「及是否同意专业调剂选项」 |
| `admit_method` | `parallel` | 「实行平行志愿…分数优先，遵循志愿，一轮投档」 |
| `ratio` | 1:1（原则上 ≤105%） | 「调档比例原则上控制在105%以内」 |
| `collect_count` | 不固定（记 0） | 「如有计划空额，公开征集志愿」 |

**同分排序**：总分（区分首选科目）→ ①语文+数学之和 → ②语文或数学单科最高 → ③外语 → ④首选科目 → ⑤再选科目最高 → ⑥再选科目次高

**志愿单位录入格式**：4 位院校代号 + 3 位专业组号 + 组内 2 位专业代号
**填报时间**：6月30日 8:00 – 7月3日 18:00，允许 2 次修改
**特殊计划**：国家专项/高校专项/地方专项/定向西藏/少数民族预科班/边防军人子女预科班 —— **均在普通本科批内填报**，限有资格者

> 来源：<https://gaokao.haedu.cn/145/424/2026/0701/155718.html>
> 交叉核对（同分规则 + 105%）：<https://gaokao.haedu.cn/501/553/2026/0427/151635.html>

### 3.2 江西 2026 · 本科批次

| 字段 | 值 | 官方原文依据 |
|---|---|---|
| `mode` | `group`（院校专业组） | — |
| `volunteer_count` | **45** | 「平行志愿栏：设45个院校专业组」 |
| `majors_per_group` | **6** | 「均设6个专业志愿及是否服从专业调剂志愿」 |
| `has_adjust` | **true** | 同上 |
| `admit_method` | `parallel` | 「分数优先、遵循志愿」 |
| `ratio` | **1:1** | 「所有平行志愿投档比例均为招生计划执行数1:1」 |
| `collect_count` | **20**（2 次征集） | 「本批次安排2次征集志愿，均设20个院校专业组平行志愿」 |

**同分排序**：与文化总成绩相同 → ①语文+数学之和 → ②语文或数学单科最高 → ③外语 → ④首选科目 → ⑤再选科目最高 → ⑥再选科目次高；全同则一并投出
**征集降分**：控制线下 **20 分**内逐分下降投档（平行志愿一次投档，**退档不补投，只征集**）
**免补投**：平行志愿只进行一轮投档，因退档出现缺额的**不补充投档**

**2026 三大变化**（务必在作品说明中体现）：
1. 原则上按专业招生、严控大类招生
2. 专业组内各专业**选科要求必须一致**（调剂更"纯"）
3. 高校专项改为**省级统一审核**、纳入本科批平行志愿
4. ⚠️ **2026 起不再公开各专业组投档线**，仅在省平台对本人定向发布 → 直接影响数据获取策略

> 来源：<http://www.jxeea.cn/jxsjyksy/dtxx67/content/content_2065264535121223680.html>
> 交叉核对：《江西省2026年普通高校招生工作实施意见》<http://www.jxeea.cn/jxsjyksy/gsgg91/content/content_2039911996485861376.html>

---

## 四、⚠️ 口径断裂（最重要的一条）

| 省份 | 首年新高考 | 之前体系 |
|---|---|---|
| 河南 | **2025** | 文理科 + 院校+专业（本科一批/二批） |
| 江西 | **2024** | 文理科 + 院校+专业 |

**后果**：
- 2017–2023 的「科类」是理科/文科，与现在的「物理类/历史类」**不是一回事**
- 跨年比较**必须按位次、不能按分数**
- 导入脚本必须强制标记 `exam_system`（本文件每条规则都带该字段）

数据集中 `subject_req` 按省 × 年整块缺失，正是这个制度原因（详见 `data/datasets/数据集核验报告.md` §4.1）。

---

## 五、字段对照（→ 第 7 章 `province_exam_rule`）

| 第 7 章字段 | 本文件字段 | 备注 |
|---|---|---|
| `id` | `id` | 形如 `CERT-HENAN-2026-BK` |
| `province` | `province` / `province_code` | 补了 6 位区划码，便于程序匹配 |
| `year` | `year` | ★ 三表都带 year（第 7 章要求） |
| `batch` | `batch` / `batch_code` | `batch_code` 为程序用稳定标识 |
| `mode` | `mode` | `group` / `major_school` / `school_major` |
| `volunteer_count` | `volunteer_count` | — |
| `majors_per_group` | `majors_per_group` | — |
| `has_adjust` | `has_adjust` | — |
| `admit_method` | `admit_method` | `parallel` / `single` |
| `ratio` | `ratio` | — |
| `tie_rule` | `tie_rule` + `tie_rule_fields[]` | 原文 + 机器可读排序键序列 |
| `mutex_groups` | `mutex_groups`（json） | 兼报限制 |
| `collect_count` | `collect_count` + `collect_note` | 不固定时留 0 并说明 |
| `source_id` | `source_id` | 已在 `source-table.json` 登记 |

**额外补充字段**（第 7 章未定义，供 ② 参考，若不要可忽略）：
`exam_system`、`first_new_gaokao_year`、`category_group`、`extra_volunteers[]`、`special_plan_note`、`filling_note`、`source_excerpt`

---

## 六、校验

```bash
# 专用校验（三要素 + 枚举 + 数值 + 唯一性 + source_id 存在性 + 口径断裂）
python data/scripts/validate_exam_rule.py

# 团队统一校验（已在 SCHEMA_BY_KIND 中新增 province_exam_rule）
python data/scripts/validate.py data/dictionaries/province-exam-rule.json --kind province_exam_rule
```

当前结果：**7/7 通过，0 错误**；唯一警告为主动标注的 `schema_only`。

---

## 七、给 ② 的对接说明

1. **渲染志愿表**读取 `mode` / `volunteer_count` / `majors_per_group` / `has_adjust`；
   `mode=group` 渲染「组 + 组内 6 专业 + 调剂」，`mode=major_school` 渲染「1 专业 + 1 院校」（无调剂）。
2. **同分排序**用 `tie_rule_fields[]` 序列（已是机器可读的键名数组）。
3. **`collect_count=0` 不代表「0 个名额」**，读 `collect_note` 判断。
4. **必须按 `year` 过滤**，禁止跨年份套用（尤其别拿 2026 的 48 组去渲染 2024 数据）。
5. 江西 2026 **不再公开专业组投档线** —— 若设计「我的分数能否进某组」功能，江西 2026 需降级为「不提供」而不是编造。

---

## 八、待办 / 需确认

- [ ] 与队长确认：其他 29 省是否也按本结构先建 `schema_only` 骨架（还是留空由产品层显示「规则待接入」）
- [ ] 与 ② 确认：`tie_rule_fields` 这套键名是否对齐其排序实现
- [ ] 补充：河南/江西 2022–2025 各年规则（待官方文件核实后再加，不编造）
- [ ] 体检限制表（`physical_restriction`）为队长/算法成员任务（文档 §4.2），不属本文件

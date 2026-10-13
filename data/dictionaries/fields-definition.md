# 数据字段定义表（数据工程 ③）

> 起草人：徐（③ 数据工程）｜ 日期：2026-10-11（D3）
> 用途：为采集、清洗、入库提供**唯一口径依据**；供 ② 后端建表、④ 算法切片的字段对齐
> 状态：**初稿待评审** —— 字段名与口径需 ② 确认后冻结

---

## 一、为什么需要这份文档

**"录取分""位次"这类词，每个省、每份资料的定义都不一样。** 如果口径不先写死，会出现：

- 采集的人按一种理解抓，入库的人按另一种理解建表 → 数据错位
- 同一个字段在不同批次里含义不同 → 前端展示矛盾
- 后期发现口径不对 → 全部数据返工

**所以：先定口径，再采数据。** 本文档就是那本"字典"。

---

## 二、通用硬性要求（来自第 7 章）

1. **来源三要素**：所有事实表必须含 `source_name`、`source_url`、`year`（或外键 `source_id`）。**缺失拒绝入库。**
2. 每表含 `created_at`、`updated_at`。
3. 枚举字段用常量，**禁止魔法值**。
4. 涉及用户条件（省份/科类/户籍）的表必须带对应过滤字段并**建索引**。
5. `knowledge_chunk.embedding` 维度固定 **512**，写入前 L2 归一化。

---

## 三、核心口径定义（★ 最重要，请重点确认）

### 3.1 录取相关

| 字段 | 口径定义 | 单位/格式 | 备注 |
|---|---|---|---|
| `min_score` | **该院校该专业（或专业组）当年在该省该批次录取的最低投档总分** | 整数，分 | 不含加分则注明；含政策加分须标注 |
| `min_rank` | **对应 `min_score` 的全省累计位次**（一分一段表中该分数的最低累计位次） | 整数 | 与 `score_segment` 表口径必须一致 |
| `avg_score` | 该校该专业录取考生的平均分 | 整数，分 | 若无官方发布则留空，**不得估算** |
| `plan_count` | 招生计划人数 | 整数 | 以官方招生计划为准 |

> ⚠️ **关键分歧点（必须确认）**：`min_score` 是**院校专业组最低分**还是**具体专业最低分**？
> 河南自 2025 年起实行新高考，投档单位变化，需 ② 和队长明确。
> **我的建议**：以**官方公布的投档单位为准**，并在 `source_name` 里注明是哪一级。

### 3.2 位次与一分一段

| 字段 | 口径定义 | 格式 |
|---|---|---|
| `score` | 分数 | 整数 |
| `cumulative_rank` | **该分数（含）以上的累计人数**，即"累计位次" | 整数 |
| `subject_type` | 科类 | `物理类` / `历史类`（新高考）；老高考为 `理科`/`文科` |

> ⚠️ **正反查询口径**：
> - **正查（分数→位次）**：用 `score` 查 `cumulative_rank`
> - **反查（位次→分数）**：给出位次，落到哪个分数区间 → 取该位次对应的分数
> 反查存在**区间归属**问题（如位次 1000 落在 620 分区间内），需明确取"该位次所在分数的下界"。

### 3.3 专项区域

| 字段 | 口径定义 |
|---|---|
| `county_name` | 县（区）正式名称，**去除"省""市"前缀，保留"县""区"后缀**，如 `兰考县`、`固始县` |
| `county_code` | 国家统计局**行政区划代码**（6 位），如 `410225` |

> ⚠️ **县名匹配规则**（影响 `region-check` 接口）：
> 用户可能输入"兰考""兰考县"甚至"河南省兰考县"，**必须有统一的归一化规则**。
> **建议**：优先按 `county_code` 精确匹配；无 code 时按县名模糊匹配并去后缀。

### 3.4 户籍与学籍（资格判定核心）

| 字段 | 口径定义 | 取值 |
|---|---|---|
| `household_type` | 户籍类型 | `农村` / `城镇`（**仅两值**，无第三态） |
| `household_years` | 户籍**连续**年限（不是累计） | 整数，年 |
| `enrollment_years` | 学籍**连续**年限 | 整数，年 |
| `parent_household_local` | 法定监护人户籍是否在当地 | boolean |

> ⚠️ **"未提供"的处理**：契约明确「缺省时按未提供处理，**不得默认成立**」。
> 即 `household_type` 为 `null` 时，不能推断为"城镇"或"农村"，判定结果为"待补充"。

---

## 四、我主责的表（逐表字段清单）

### 4.1 `source` 来源登记表（★ 所有数据的凭据）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `source_name` | varchar | 来源名称，如「河南省教育考试院」 |
| `source_url` | varchar | 原始链接 |
| `year` | int | 数据年份 |
| `source_type` | enum | `官方` / `高校官网` / `权威媒体` / `其他` |
| `fetched_at` | datetime | 采集时间 |

### 4.2 `pathway` 途径字典（26 类）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `name` | varchar | 途径名称 |
| `category` | varchar | 类别（见途径清单） |
| `batch` | varchar | 录取批次 |
| `target_group` | varchar | 面向人群 |
| `apply_time` | varchar | 申请时间节点 |
| `description` | text | 简介 |
| `priority` | enum | `P0` / `P1` / `P2` |
| `data_status` | enum | `available` / `partial` / `schema_only` / `unavailable` |
| `source_id` | int FK | → `source` |

### 4.3 `pathway_eligibility` 资格规则

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `pathway_id` | int FK | → `pathway` |
| `province` | varchar | 适用省份 |
| `rule_type` | enum | `户籍` / `学籍` / `区域` / `成绩` |
| `rule_desc` | text | 规则描述（**给用户看的人话**） |
| `params` | json | 规则参数（阈值等，**给引擎算的结构**） |
| `source_id` | int FK | → `source` |

**`params` JSON 结构建议**：

```json
{
  "household_years_min": 3,
  "enrollment_years_min": 3,
  "household_type_in": ["农村"],
  "require_parent_local": true
}
```

### 4.4 `pathway_region` 专项实施区域

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `pathway_id` | int FK | → `pathway` |
| `province` | varchar | 省份 |
| `county_name` | varchar | 县名（**归一化后**） |
| `county_code` | varchar(6) | 行政区划码 |
| `source_id` | int FK | → `source` |

> 数据量预期：国家专项**38 县**、地方专项**若干县**、高校专项**若干县**。

### 4.5 `school` 院校基础库（约 300 所本科）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `name` / `code` | | 名称、院校代码 |
| `province` / `city` | varchar | 所在地 |
| `level` | varchar | 层次（本科/专科、985/211/双一流） |
| `type` | varchar | 类型（综合/理工/师范…） |
| `ownership` | varchar | 办学性质（公办/民办） |
| `website` | varchar | 官网 |
| `intro` | text | 简介 |

**索引**：`province`、`level`、`name`

### 4.6 `major` 专业基础库

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `name` / `code` | | |
| `category` | varchar | 学科门类 |
| `first_class` | varchar | 一级学科 |
| `degree` | varchar | 授予学位 |

### 4.7 `school_major_score` 院校专业录取分（★ 核心事实表）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `school_id` / `major_id` | FK | |
| `province` | varchar | 省份 |
| `year` | int | 年份（**2022 / 2024 / 2025**） |
| `batch` | varchar | 批次 |
| `pathway_id` | int FK | 途径 |
| `subject_type` | varchar | 科类 |
| `min_score` / `min_rank` / `avg_score` | | 见 3.1 口径 |
| `plan_count` | int | 计划数 |
| `source_id` | int FK | |

**索引**：`(province, year, batch, pathway_id)`

### 4.8 `score_segment` 一分一段表

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `province` / `year` / `subject_type` | | |
| `score` | int | 分数 |
| `cumulative_rank` | int | 累计位次 |
| `source_id` | int FK | |

**索引**：`(province, year, subject_type, score)`

### 4.9 `school_profile` 院校画像

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `school_id` | | |
| `tuition_range` | varchar | 学费区间 |
| `accommodation_fee` | varchar | 住宿费 |
| `campus_list` | json | 校区列表 |
| `established_year` | int | 建校年份 |
| `master_phd_points` | varchar | 硕博点 |
| `first_class_major_count` | int | 一流本科专业数 |
| `faculty_count` | int | 师资人数 |
| `student_faculty_ratio` | varchar | 师生比 |
| `source_id` | int FK | |

### 4.10 `school_life` 生活信息（★ 合规重点）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` / `school_id` | | |
| `category` | varchar | 分类（住宿/食堂/交通…） |
| `content` | text | 内容 |
| `source_type` | enum | 来源类型（官方/学生评价/论坛） |
| `reliability` | enum | 可靠性（高/中/低） |
| `source_name` / `source_url` / `year` | | 三要素 |

> ⚠️ 第 7 章要求：**非官方信息默认折叠并显示"仅供参考"**。

---

## 五、字段名冲突（部分已由契约 v1.2 裁定）

契约与第 7 章 `user_profile` 表的字段名曾有差异，其中**户籍类字段已裁定**：

- **户籍所在县**：统一用 `home_county`；**户籍县行政区划码**：统一用 `home_county_code`。
  不再存在 `household_county`（契约 v1.2 裁定，Alembic 0006 已重命名）。
  见 `docs/api-contract.md` 第 2 节「字段名裁定」。

其余字段名冲突：

| 概念 | 契约字段名 | 第 7 章表字段名 | 需确认 |
|---|---|---|---|
| 学籍年限 | `enrollment_years` | `school_years` | 以哪个为准？ |
| 学籍所在县 | `enrollment_county` | （未定义） | 第 7 章缺 |

> **原则**：以契约为准（契约是前后端唯一依据，且是更新的）。第 7 章的表定义也需同步，
> 否则 ② 建表时会产生偏差。**请 ② 明确。**

---

## 六、枚举常量清单（禁止魔法值）

| 枚举 | 取值 |
|---|---|
| `priority` | `P0` / `P1` / `P2` |
| `data_status` | `available` / `partial` / `schema_only` / `unavailable` |
| `rule_type` | `户籍` / `学籍` / `区域` / `成绩` |
| `subject_type` | `物理类` / `历史类` /（老高考）`理科` / `文科` |
| `household_type` | `农村` / `城镇` |
| `source_type` | `官方` / `高校官网` / `权威媒体` / `其他` |
| `reliability` | `高` / `中` / `低` |
| `strategy` | `冲` / `稳` / `保` |
| `priority`（偏好） | `城市优先` / `专业优先` |

---

## 七、待确认事项

| # | 事项 | 找谁 | 紧急度 |
|---|---|---|---|
| 1 | `min_score` 是专业组还是专业级？ | ② 队长 | ★高 |
| 2 | 位次反查的区间归属规则 | ② | 中 |
| 3 | 字段名冲突以契约还是第 7 章为准？ | ② | ★高 |
| 4 | 县名归一化规则是否认可 | ② | 中 |
| 5 | `params` JSON 结构是否符合引擎预期 | ② ④ | ★高 |

---

## 八、依据出处

- 通用要求与表结构 → `开发产品书_智选志愿.md` 第 7 章
- 档案字段 → `docs/api-contract.md` 第 2 节
- 规则 JSON → 同书 8.3 节
- 生活信息合规 → 同书 7.4 节 + 第 14 章风险

# 数据样本包（`data/samples/`）

> 负责人：③ 数据工程（徐）｜ 首版：2026-10-12 ｜ 最近同步：2026-10-14
> 生成脚本：`data/scripts/build_samples.py`（**条数由脚本按实际数据注入，勿手改本表**）
>
> 2026-10-14 同步内容：① 修 `pathway_eligibility` 悬空 `pathway_id`（`general-batch`→`normal-batch`）；
> ② `data_status` 枚举改回契约 v1.3 四值；③ 补齐 `year` 字段（此前样本缺三要素之一）；
> ④ `school`/`school_major_score` 的空值边界行改为按**真实空值**选取（原选取条件已失效）。

## 用途

② 的**建表 + Alembic 迁移（M0-3）**尚未完成。本样本包让 ② **不必等全量数据**
即可验证：表结构、主外键、字段名、枚举取值、来源三要素、导入流程、边界处理。

## ⚠️ 性质说明

- 本包是**真实数据的截取**，**不是**编造数据（红线：宁可缺，不可猜）。
- 本包是 **sample（抽样）**，**不是全量**，**不得用于生产展示**。
- 字段名 / 枚举 / 三要素与全量产物**完全一致**，可直接入库。
- 每个文件都带 `_sample_meta`（`nature: "sample"`），便于下游区分。

## 文件清单

| 文件 | 目标表 | 条数 | 覆盖要点 |
|---|---|---|---|
| `source.json` | `source` | 17（全量） | 来源登记，② 建外键的依据 |
| `pathway.json` | `pathway` | 26（全量） | P0 要求的 26 类升学途径 |
| `pathway_region.json` | `pathway_region` | 12 | 专项区域，**含 `county_code`** |
| `pathway_eligibility.json` | `pathway_eligibility` | 11（全量） | 资格规则 + `params` JSON |
| `province_exam_rule.json` | `province_exam_rule` | 7（全量） | 志愿模式，含 `mode` 枚举三态 |
| `school.json` | `school` | 12 | 名校 9 + 空值边界 3 |
| `score_segment.json` | `score_segment` | 12 | 老高考/新高考 + 多批次 |
| `school_major_score.json` | `school_major_score` | 14 | 含 `school_id` 空、`subject_type` 空、`min_score` 小数三类边界 |

## ② 导入注意

1. **`source` 必须先导**：其他表的 `source_id` 依赖它。
2. **枚举以 `data/scripts/validate.py` 为准**（**契约 v1.3**）：
   - `data_status` ∈ `{available, partial, schema_only, unavailable}`
     —— ⚠️ 旧文档写过的 `{verified, schema_only, pending}` **已废弃**，请勿再按它建 CHECK。
   - `source_type` ∈ `{官方, 高校官网, 权威媒体, 其他}`
   - `priority` ∈ `{P0, P1, P2}`
   - `province_exam_rule.mode` ∈ `{group, major_school, school_major}`
3. **样本里刻意保留的"问题行"**（② 测边界用，勿当 bug）：
   - `school.json`：`type` 空 1 条、`website` 空 3 条、`intro` 空 2 条 → 应允许 NULL
   - `school_major_score.json`：2 条 `school_id` 为空 → 应允许 NULL 并标注
   - `school_major_score.json`：2 条 `subject_type` 为空 → 应允许空串
   - `school_major_score.json`：2 条 `min_score` 带**小数**（原始 CSV 即如此，非官方投档线口径）
     → ③ 灌库时该类值**置 NULL**（宁可缺不可猜，台账 G3）；② 若认为应保留小数，
       需把列改 `NUMERIC(6,2)` 并同步改契约口径 —— **待裁**
   - `score_segment.json` / `school_major_score.json`：`data_status = schema_only`
     → 界面须如实标注（**不是** `pending`，该值已废弃）
     - ⚠️ **样本是 mock，真实产物不是**：样本按契约 L346「纯 Mock 必须以 `schema_only` 标注」
       保留 `schema_only`；**真实一分一段产物**的状态见
       `data/dictionaries/dataset-verification.json`（E3 已核实 4 组 → `available`，
       其余 → `partial`）。② 灌真实数据时**以该登记表为准**，勿沿用样本值。
4. **字段名口径**（第 7 章 vs 契约曾有冲突，本包统一用第 7 章名）：
   - `score_segment.cumulative_rank`（不是 `rank`）
   - `school_major_score.min_score` / `min_rank` / `avg_score`

## 复现

```bash
python data/scripts/build_samples.py
```

## 预期校验结果

| 文件 | `validate.py` 结果 | 说明 |
|---|---|---|
| `source` / `pathway_region` / `pathway_eligibility` | ✅ 通过 | |
| `pathway` / `school` / `score_segment` | ✅ 通过 + 警告 | 警告为 `data_status=schema_only`（设计如此） |
| `school_major_score` | ⚠️ 2 处 ERROR + 警告 | **ERROR 是刻意留的边界行**（`school_id` 为空，用于测 NULL 处理） |

> ⚠️ `school_major_score.json` 的空 `school_id` ERROR**不是数据缺陷**，是**故意保留**的边界样本。
> ② 建表时应允许 `school_id` 为 NULL（对应"院校库无此校"的客观缺失）。
> ③ 侧全量灌库时这类行按"宁可缺，不可猜"**不入库**，进台账待补采。

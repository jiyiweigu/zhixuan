# 数据样本包（`data/samples/`）

> 负责人：③ 数据工程（徐）｜ 生成：2026-10-12
> 生成脚本：`data/scripts/build_samples.py`

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
| `source.json` | `source` | 15（全量） | 来源登记，② 建外键的依据 |
| `pathway.json` | `pathway` | 26（全量） | P0 要求的 26 类升学途径 |
| `pathway_region.json` | `pathway_region` | 12 | 专项区域，**含 `county_code`** |
| `pathway_eligibility.json` | `pathway_eligibility` | 11（全量） | 资格规则 + `params` JSON |
| `province_exam_rule.json` | `province_exam_rule` | 7（全量） | 志愿模式，含 `mode` 枚举三态 |
| `school.json` | `school` | 10 | 含 `type`/`website`/`intro` 空边界 |
| `score_segment.json` | `score_segment` | 12 | 老高考/新高考 + 多批次 |
| `school_major_score.json` | `school_major_score` | 12 | 含 `school_id` 空、`subject_type` 空边界 |

## ② 导入注意

1. **`source` 必须先导**：其他表的 `source_id` 依赖它。
2. **枚举以 `data/scripts/validate.py` 为准**：
   - `data_status` ∈ `{available, partial, schema_only, unavailable}`（契约四值）
   - `source_type` ∈ `{官方, 高校官网, 权威媒体, 其他}`
   - `priority` ∈ `{P0, P1, P2}`
   - `province_exam_rule.mode` ∈ `{group, major_school, school_major}`
3. **样本里刻意保留的"问题行"**（② 测边界用，勿当 bug）：
   - `school.json`：`type`/`website`/`intro` 为空 → 应允许 NULL
   - `school_major_score.json`：2 条 `school_id` 为空 → 应允许 NULL 并标注
   - `school_major_score.json`：2 条 `subject_type` 为空 → 应允许空串
   - `score_segment.json` / `school_major_score.json`：`data_status = pending`（渠道数据未核实；按契约 §8.7 须映射为 `schema_only` 后方可出接口）→ 界面须如实标注
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
| `pathway` / `school` / `score_segment` | ✅ 通过 + 警告 | 警告为 `data_status=pending`（设计如此；按契约映射为 `schema_only`） |
| `school_major_score` | ⚠️ 2 处 ERROR + 警告 | **ERROR 是刻意留的边界行**（第 9、10 条 `school_id` 为空，用于测 NULL 处理） |

> ⚠️ `school_major_score.json` 的 2 处 ERROR **不是数据缺陷**，是**故意保留**的边界样本。
> ② 建表时应允许 `school_id` 为 NULL（对应"院校库无此校"的客观缺失）。

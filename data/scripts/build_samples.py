#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""小样本包生成脚本（data/samples/ → 供 ② 后端做导入联调）

目的
    ② 的建表 + Alembic 迁移（M0-3）尚未完成。为让 ② **不必等全量数据**即可验证
    表结构、外键、字段口径与导入流程，③ 先产出一份**小而真实**的样本包：
    每张表 5~10 条，**结构、字段名、枚举、来源三要素与全量数据完全一致**。

红线
    1. **样本必须是真实数据**，不得编造（直接从全量产物截取）。
    2. 样本必须覆盖**边界情形**（空值、口径断裂、脏数据），否则 ② 测不出问题。
    3. 样本文件独立、可单独入库，**不与全量数据混淆**（明确标注 sample）。

产出
    data/samples/
      ├── README.md              # 用法与字段说明
      ├── source.json            # source 表（全量 15 条，本就很小）
      ├── pathway.json           # pathway（26 类，全量）
      ├── pathway_region.json    # pathway_region（取 10 条，覆盖 2 类途径）
      ├── pathway_eligibility.json
      ├── province_exam_rule.json
      ├── school.json            # 10 条（含边界：type/website/intro 为空）
      ├── score_segment.json     # 12 条（覆盖老高考/新高考）
      └── school_major_score.json# 12 条（含 school_id 为空、subject_type 为空）
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = DATA / "samples"

SAMPLE_META = {
    "purpose": "供 ② 后端做建表/导入联调的小样本包",
    "owner": "徐（③ 数据工程）",
    "generated_at": "2026-10-12",
    "nature": "sample — 真实数据截取，非全量，不得用于生产展示",
    "note": "字段名/枚举/来源三要素与全量产物完全一致；覆盖空值与脏数据边界。",
}


def load(rel: str):
    return json.loads((DATA / rel).read_text(encoding="utf-8"))


def write(name: str, payload: dict, table: str, note: str = ""):
    payload = {
        "_sample_meta": {**SAMPLE_META, "target_table": table, "note": note},
        **payload,
    }
    (OUT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    n = payload.get("count", _count_rows(payload))
    print(f"  ✓ {name:28s} {n:>5} 行")


def _count_rows(payload: dict) -> int:
    for k in ("records", "pathways", "regions", "rules", "segments", "scores",
              "sources", "schools", "items", "rows"):
        v = payload.get(k)
        if isinstance(v, list):
            return len(v)
    return 0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    print("生成小样本包 data/samples/：")

    # ── 1. source（全量 15 条，本就很小，直接给全） ──
    src = load("sources/source-table.json")
    write("source.json", {"count": len(src["sources"]), "sources": src["sources"]},
          "source", "全量给齐（仅 15 条），② 可直接入库做外键依据。")

    # ── 2. pathway（26 类，全量） ──
    pw = load("dictionaries/pathways-26.json")
    write("pathway.json", {"count": len(pw["pathways"]), "pathways": pw["pathways"]},
          "pathway", "全量 26 类（P0 清单要求）。")

    # ── 3. pathway_region（取 12 条，覆盖 2 类途径 + 含 county_code） ──
    reg = load("dictionaries/pathway-regions.json")
    regions = reg["regions"]
    nat = [r for r in regions if r["pathway_id"] == "national-special"][:8]
    col = [r for r in regions if r["pathway_id"] == "college-special"][:4]
    picked = nat + col
    write("pathway_region.json", {"count": len(picked), "regions": picked},
          "pathway_region",
          "12 条：国家专项 8 + 高校专项 4，均含 county_code（第6章要求精确匹配优先）。")

    # ── 4. pathway_eligibility（全 11 条） ──
    el = load("dictionaries/pathway-eligibility.json")
    write("pathway_eligibility.json",
          {"count": len(el["rules"]), "rules": el["rules"]},
          "pathway_eligibility", "全量 11 条资格规则。")

    # ── 5. province_exam_rule（全 7 条） ──
    per = load("dictionaries/province-exam-rule.json")
    write("province_exam_rule.json",
          {"count": len(per["rules"]), "rules": per["rules"]},
          "province_exam_rule",
          "全量 7 条。注意 CERT-HENAN-2026-BK-OLD 为 schema_only（数值未核实，禁止使用）。")

    # ── 6. school（10 条，含 type/website/intro 为空的边界） ──
    sch = load("schools/schools_merged.json")["records"]
    # 挑有代表性的：河南本省 + 京沪 + 一所 ownership 缺失的
    picked_schools = []
    seen = set()
    for want in ["郑州大学", "河南大学", "北京大学", "清华大学", "复旦大学",
                 "上海交通大学", "浙江大学", "武汉大学", "中山大学"]:
        for r in sch:
            if r["name"] == want and r["id"] not in seen:
                picked_schools.append(r)
                seen.add(r["id"])
                break
    # 补一条 ownership 为空的（边界）
    for r in sch:
        if not r.get("ownership") and r["id"] not in seen:
            picked_schools.append(r)
            seen.add(r["id"])
            break
    write("school.json",
          {"count": len(picked_schools), "schools": picked_schools},
          "school",
          f"{len(picked_schools)} 条。含边界：type/website/intro 均为空（待补，见采集报告§5）。")

    # ── 7. score_segment（12 条：老高考+新高考，含批次断裂） ──
    segs = []
    for f, n in [("2024_河南", 4), ("2025_河南", 4), ("2024_江西", 4)]:
        s = load(f"score_segment/score_segment_{f}.json")["segments"]
        # 取每个 (subject_type,batch) 组的前几条，保证批次齐全
        groups: dict[tuple, list] = {}
        for x in s:
            groups.setdefault((x["subject_type"], x["batch"]), []).append(x)
        got = 0
        for k, g in groups.items():
            if got >= n:
                break
            segs.append(g[0])
            got += 1
    write("score_segment.json", {"count": len(segs), "segments": segs},
          "score_segment",
          "覆盖老高考(文/理)+新高考(物理/历史)与多批次，演示 batch 不可合并。字段名用第7章 cumulative_rank。")

    # ── 8. school_major_score（12 条，含两张"问题行"） ──
    scores = []
    fam = load("school_major_score/school_major_score_2025_河南.json")["scores"]
    # 正常行（有 school_id）
    ok = [x for x in fam if x["school_id"]][:8]
    scores += ok
    # 边界1：school_id 为空（院校改名，未挂上）
    bad = [x for x in fam if not x["school_id"]][:2]
    scores += bad
    # 边界2：subject_type 为空（2024 两省）
    fam24 = load("school_major_score/school_major_score_2024_河南.json")["scores"]
    empty_cat = [x for x in fam24 if not x["subject_type"]][:2]
    scores += empty_cat
    write("school_major_score.json", {"count": len(scores), "scores": scores},
          "school_major_score",
          f"{len(scores)} 条。含边界：{len(bad)} 条 school_id 空（院校改名）、"
          f"{len(empty_cat)} 条 subject_type 空（2024 category 整列缺失）。")

    # ── README ──
    (OUT / "README.md").write_text(README, encoding="utf-8")
    print(f"  ✓ README.md")
    print("\n样本包就绪。② 可直接按文件逐表导入验证。")
    return 0


README = """# 数据样本包（`data/samples/`）

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
   - `data_status` ∈ `{verified, schema_only, pending}`
   - `source_type` ∈ `{官方, 高校官网, 权威媒体, 其他}`
   - `priority` ∈ `{P0, P1, P2}`
   - `province_exam_rule.mode` ∈ `{group, major_school, school_major}`
3. **样本里刻意保留的"问题行"**（② 测边界用，勿当 bug）：
   - `school.json`：`type`/`website`/`intro` 为空 → 应允许 NULL
   - `school_major_score.json`：2 条 `school_id` 为空 → 应允许 NULL 并标注
   - `school_major_score.json`：2 条 `subject_type` 为空 → 应允许空串
   - `score_segment.json` / `school_major_score.json`：`data_status = pending` → 界面须如实标注
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
| `pathway` / `school` / `score_segment` | ✅ 通过 + 警告 | 警告为 `data_status=pending`（设计如此） |
| `school_major_score` | ⚠️ 2 处 ERROR + 警告 | **ERROR 是刻意留的边界行**（第 9、10 条 `school_id` 为空，用于测 NULL 处理） |

> ⚠️ `school_major_score.json` 的 2 处 ERROR **不是数据缺陷**，是**故意保留**的边界样本。
> ② 建表时应允许 `school_id` 为 NULL（对应"院校库无此校"的客观缺失）。
"""


if __name__ == "__main__":
    sys.exit(main())

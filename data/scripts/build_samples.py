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

    # ── 1. source（全量，本就很小，直接给全） ──
    src = load("sources/source-table.json")
    src_rows = src["sources"]
    write("source.json", {"count": len(src_rows), "sources": src_rows},
          "source", f"全量给齐（{len(src_rows)} 条），② 可直接入库做外键依据。")

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

    # ── 6. school（名校 9 条 + 真实存在的空字段边界行） ──
    sch = load("schools/schools_merged.json")["records"]
    # 挑有代表性的：河南本省 + 京沪
    picked_schools = []
    seen = set()
    for want in ["郑州大学", "河南大学", "北京大学", "清华大学", "复旦大学",
                 "上海交通大学", "浙江大学", "武汉大学", "中山大学"]:
        for r in sch:
            if r["name"] == want and r["id"] not in seen:
                picked_schools.append(r)
                seen.add(r["id"])
                break
    # 边界行：从**真实数据**中挑 type/website/intro 为空的院校（取真实空值，不编造、不填充）
    # ⚠️ 历史坑：原实现找的是 ownership 为空的校，该字段补全后已无此类行 ⇒
    #    样本包「覆盖 school 空字段边界」的承诺会静默失效（README 仍写着 10 条）。
    boundary: list[tuple[str, str]] = []
    for field in ("type", "website", "intro"):
        for r in sch:
            if r["id"] in seen:
                continue
            if not str(r.get(field) or "").strip():
                picked_schools.append(r)
                seen.add(r["id"])
                boundary.append((r["name"], field))
                break
    n_empty = {f: sum(1 for r in picked_schools if not str(r.get(f) or "").strip())
               for f in ("type", "website", "intro")}
    empty_desc = "、".join(f"`{k}` 空 {v} 条" for k, v in n_empty.items() if v) or "（无空字段）"
    write("school.json",
          {"count": len(picked_schools), "schools": picked_schools},
          "school",
          f"{len(picked_schools)} 条 = 名校 {len(picked_schools) - len(boundary)} + "
          f"边界 {len(boundary)}（{empty_desc}）⇒ ② 应允许这些字段为 NULL。")

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

    # ── 8. school_major_score（含三类"问题行"） ──
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
    # 边界3：min_score 上游带小数（疑为均值而非投档线）—— 表列是 INTEGER，
    #        ② 若按样本建表就看不到这个冲突，必须让它出现在样本里（真实行，未改值）。
    #        ⚠️ 小数**只**出现在 2022_河南（其余 7 个文件为 0），故取样文件必须是它。
    used = {id(x) for x in scores}
    fam22 = load("school_major_score/school_major_score_2022_河南.json")["scores"]
    dec = [x for x in fam22
           if id(x) not in used
           and isinstance(x.get("min_score"), float)
           and x["min_score"] != int(x["min_score"])][:2]
    scores += dec
    write("school_major_score.json", {"count": len(scores), "scores": scores},
          "school_major_score",
          f"{len(scores)} 条。含边界：{len(bad)} 条 school_id 空（院校改名）、"
          f"{len(empty_cat)} 条 subject_type 空（2024 category 整列缺失）、"
          f"{len(dec)} 条 min_score 带小数（上游疑为均值，表列是 INTEGER ⇒ 需取整口径）。")

    # ── README ──
    ctx = {
        "n_source": len(src_rows),
        "n_pathway": len(pw["pathways"]),
        "n_region": len(picked),
        "n_elig": len(el["rules"]),
        "n_per": len(per["rules"]),
        "n_school": len(picked_schools),
        "n_school_famous": len(picked_schools) - len(boundary),
        "n_school_boundary": len(boundary),
        "school_empty_desc": empty_desc,
        "n_seg": len(segs),
        "n_sms": len(scores),
        "n_bad": len(bad),
        "n_empty_cat": len(empty_cat),
        "n_dec": len(dec),
    }
    (OUT / "README.md").write_text(README % ctx, encoding="utf-8")
    print(f"  ✓ README.md")
    print("\n样本包就绪。② 可直接按文件逐表导入验证。")
    return 0


README = """# 数据样本包（`data/samples/`）

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
| `source.json` | `source` | %(n_source)s（全量） | 来源登记，② 建外键的依据 |
| `pathway.json` | `pathway` | %(n_pathway)s（全量） | P0 要求的 26 类升学途径 |
| `pathway_region.json` | `pathway_region` | %(n_region)s | 专项区域，**含 `county_code`** |
| `pathway_eligibility.json` | `pathway_eligibility` | %(n_elig)s（全量） | 资格规则 + `params` JSON |
| `province_exam_rule.json` | `province_exam_rule` | %(n_per)s（全量） | 志愿模式，含 `mode` 枚举三态 |
| `school.json` | `school` | %(n_school)s | 名校 %(n_school_famous)s + 空值边界 %(n_school_boundary)s |
| `score_segment.json` | `score_segment` | %(n_seg)s | 老高考/新高考 + 多批次 |
| `school_major_score.json` | `school_major_score` | %(n_sms)s | 含 `school_id` 空、`subject_type` 空、`min_score` 小数三类边界 |

## ② 导入注意

1. **`source` 必须先导**：其他表的 `source_id` 依赖它。
2. **枚举以 `data/scripts/validate.py` 为准**（**契约 v1.3**）：
   - `data_status` ∈ `{available, partial, schema_only, unavailable}`
     —— ⚠️ 旧文档写过的 `{verified, schema_only, pending}` **已废弃**，请勿再按它建 CHECK。
   - `source_type` ∈ `{官方, 高校官网, 权威媒体, 其他}`
   - `priority` ∈ `{P0, P1, P2}`
   - `province_exam_rule.mode` ∈ `{group, major_school, school_major}`
3. **样本里刻意保留的"问题行"**（② 测边界用，勿当 bug）：
   - `school.json`：%(school_empty_desc)s → 应允许 NULL
   - `school_major_score.json`：%(n_bad)s 条 `school_id` 为空 → 应允许 NULL 并标注
   - `school_major_score.json`：%(n_empty_cat)s 条 `subject_type` 为空 → 应允许空串
   - `school_major_score.json`：%(n_dec)s 条 `min_score` 带**小数**（原始 CSV 即如此，非官方投档线口径）
     → ③ 灌库时该类值**置 NULL**（宁可缺不可猜，台账 G3）；② 若认为应保留小数，
       需把列改 `NUMERIC(6,2)` 并同步改契约口径 —— **待裁**
   - `score_segment.json` / `school_major_score.json`：`data_status = schema_only`
     → 界面须如实标注（**不是** `pending`，该值已废弃）
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
| `school_major_score` | ⚠️ %(n_bad)s 处 ERROR + 警告 | **ERROR 是刻意留的边界行**（`school_id` 为空，用于测 NULL 处理） |

> ⚠️ `school_major_score.json` 的空 `school_id` ERROR**不是数据缺陷**，是**故意保留**的边界样本。
> ② 建表时应允许 `school_id` 为 NULL（对应"院校库无此校"的客观缺失）。
> ③ 侧全量灌库时这类行按"宁可缺，不可猜"**不入库**，进台账待补采。
"""


if __name__ == "__main__":
    sys.exit(main())

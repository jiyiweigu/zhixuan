#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成「国标专业代码 → major 表行」映射（B-1 的 ③ 侧解法）

背景
----
``major`` 表主键 ``id`` 是 int 自增，``school_major_score.major_id`` 外键指向它；
而 ③ 的录取分数据里 ``major_id`` 存的是**国标专业代码字符串**（``'120203K'``）
或**专业类码**（``'0809'``）。两者类型与语义都不同位。

本脚本产出 ③ 侧解法所需的**代码维度映射与量化影响面**：

1. 845 个专业：``code`` → (name, 专业类, 学科门类, 学位注, 是否特设/国控)
2. 93 个专业类：``class_code`` → (类名, 学科门类) —— 供 major 表补「按大类招生」行
3. 统计 ``school_major_score`` 全量 116,036 行的 ``major_id`` 分布：
   命中专业码 / 命中类码 / 落空，量化 B-1 的影响面
4. 给出 ``major`` 表应灌行数建议：845 专业 + 93 专业类 = 938 行

用法::

    python data/scripts/build_major_code_map.py

产出::

    data/mappings/major-code-map.json
    data/mappings/major-code-map.csv
"""

from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAJORS = ROOT / "data" / "majors" / "majors.json"
SCORE_DIR = ROOT / "data" / "school_major_score"
OUT_DIR = ROOT / "data" / "mappings"


def load_json(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    cat = load_json(MAJORS)
    menlei = {m["menlei_code"]: m["menlei"] for m in cat.get("menlei", [])}
    classes = cat.get("classes", [])
    majors = cat.get("majors", [])

    by_code: dict[str, dict] = {}
    for m in majors:
        by_code[m["code"]] = {
            "kind": "major",
            "code": m["code"],
            "name": m["name"],
            "class_code": m["class_code"],
            "class_name": m["class_name"],
            "menlei_code": m["menlei_code"],
            "menlei": m["menlei"],
            "degree_note": m.get("degree_note"),
            "is_special": bool(m.get("is_special")),
            "is_state_controlled": bool(m.get("is_state_controlled")),
            "is_category": False,
        }
    by_class: dict[str, dict] = {}
    for c in classes:
        cc = c["class_code"]
        entry = {
            "kind": "class",
            "code": cc,
            "name": c["class_name"],
            "class_code": cc,
            "class_name": c["class_name"],
            "menlei_code": c["menlei_code"],
            "menlei": c["menlei"],
            "is_category": True,
        }
        by_class[cc] = entry
        # 类码也进统一索引，供 school_major_score 的 major_id 反查
        by_code.setdefault(cc, entry)

    # —— 量化 B-1 影响面：school_major_score 的 major_id 分布 ——
    dist = collections.Counter()
    unmatched_samples: list[dict] = []
    if SCORE_DIR.exists():
        for p in sorted(SCORE_DIR.glob("school_major_score_*.json")):
            obj = load_json(p)
            for r in obj.get("scores", []):
                mid = r.get("major_id")
                if mid in (None, ""):
                    dist["empty"] += 1
                    continue
                code = str(mid)
                if code in by_code and by_code[code]["kind"] == "major":
                    dist["hit_major"] += 1
                elif code in by_class:
                    dist["hit_class"] += 1
                else:
                    dist["miss"] += 1
                    if len(unmatched_samples) < 20:
                        unmatched_samples.append(
                            {"file": p.name, "major_id": code,
                             "major_name": r.get("major_name"), "major_code": r.get("major_code")}
                        )

    total = sum(dist.values())
    payload = {
        "meta": {
            "title": "国标专业代码 → major 表行 映射",
            "purpose": "让 ② 把 school_major_score.major_id 的国标代码转成 major 表的 int 行 id",
            "owner": "徐（③ 数据工程）",
            "generated_at": "2026-10-13",
            "source": "教育部《普通高等学校本科专业目录（2025年）》，SRC-MOE-ZHUANYE-2025",
            "usage": (
                "② 灌 major 表时：把 major_rows 全量写入（845 专业 + 93 专业类），"
                "以 code 为业务键；再建 (code → major.id) 索引，"
                "把 school_major_score 的 major_id 由代码替换为行 id。"
            ),
            "counts": {
                "menlei": len(menlei), "classes": len(classes), "majors": len(majors),
                "major_table_rows_suggested": len(majors) + len(classes),
            },
            "impact_on_school_major_score": {
                "total_rows": total,
                "hit_major_code": dist.get("hit_major", 0),
                "hit_class_code": dist.get("hit_class", 0),
                "empty_major_id": dist.get("empty", 0),
                "unmatched": dist.get("miss", 0),
                "unmatched_samples": unmatched_samples,
            },
        },
        "menlei": menlei,
        "map_by_code": by_code,
        "major_rows": [by_class[c] for c in sorted(by_class)] + majors_as_rows(majors),
        "score_major_id_unmatched_samples": unmatched_samples,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUT_DIR / "major-code-map.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    out_csv = OUT_DIR / "major-code-map.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "kind", "name", "class_code", "class_name",
                    "menlei_code", "menlei", "is_category"])
        for code in sorted(by_code):
            e = by_code[code]
            w.writerow([e["code"], e["kind"], e["name"], e.get("class_code", ""),
                        e.get("class_name", ""), e.get("menlei_code", ""),
                        e.get("menlei", ""), e.get("is_category", False)])

    print(f"专业 {len(majors)} / 专业类 {len(classes)} / 门类 {len(menlei)}")
    print(f"major 表建议行数（专业 + 专业类）：{len(majors) + len(classes)}")
    print(f"school_major_score 全量 {total} 行 major_id 分布：")
    print(f"  命中专业码 {dist.get('hit_major', 0)} | 命中类码 {dist.get('hit_class', 0)}"
          f" | 空 {dist.get('empty', 0)} | 落空 {dist.get('miss', 0)}")
    if unmatched_samples:
        print(f"  落空样例（前 {len(unmatched_samples)}）：")
        for s in unmatched_samples[:8]:
            print(f"    {s['file']} major_id={s['major_id']!r} major_name={s['major_name']!r}")
    print(f"已写出：{out_json.relative_to(ROOT)}")
    print(f"已写出：{out_csv.relative_to(ROOT)}")
    return 0


def majors_as_rows(majors: list[dict]) -> list[dict]:
    """把专业条目整理成 major 表行形状（与 by_class 的键保持一致）。"""
    rows = []
    for m in majors:
        rows.append({
            "kind": "major",
            "code": m["code"],
            "name": m["name"],
            "class_code": m["class_code"],
            "class_name": m["class_name"],
            "menlei_code": m["menlei_code"],
            "menlei": m["menlei"],
            "degree_note": m.get("degree_note"),
            "is_special": bool(m.get("is_special")),
            "is_state_controlled": bool(m.get("is_state_controlled")),
            "is_category": False,
        })
    return rows


if __name__ == "__main__":
    raise SystemExit(main())

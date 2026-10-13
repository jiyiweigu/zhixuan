#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 source 逻辑 id ↔ source 表三要素 映射（B-4 的 ③ 侧解法）

背景
----
③ 的数据产物用可读字符串 ``SRC-XXX`` 作来源标识（便于人读与跨文件追溯），
而 ``source`` 表的 ``id`` 是 **int 自增主键**。② 的
``app/services/source_guard.py::ensure_source()`` 按三要素
``(source_name, source_url, year)`` 做 lookup-or-create 拿 int id。

本脚本产出**稳定映射**，使 ② 零结构变更即可把 ``SRC-XXX`` 转成 ``source.id``::

    SRC-XXX ──(name, url, year)──▶ ensure_source() ──▶ source.id

同时扫描 ``data/`` 下所有引用了 ``source_id`` 的产物，输出「谁引用了谁」清单，
确保「数据用到的每个 SRC id 都在册」（在册 = 能在 source 表里找到/建出）。

用法::

    python data/scripts/build_source_id_map.py

产出::

    data/mappings/source-id-map.json
    data/mappings/source-id-map.csv
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_TABLE = ROOT / "data" / "sources" / "source-table.json"
OUT_DIR = ROOT / "data" / "mappings"

# 扫描引用的范围（③ 的产物目录）
SCAN_DIRS = ["data/dictionaries", "data/schools", "data/majors",
             "data/school_major_score", "data/score_segment", "data/samples"]
# 顶层键 → 记录数组键（与各产物约定一致）
ARRAY_KEYS = ("sources", "records", "rules", "regions", "scores", "segments",
              "majors", "schools", "pathways", "classes", "items", "data",
              "profiles", "life")


def load_json(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def iter_records(obj):
    """从任意产物 JSON 中尽量取出记录数组。"""
    if isinstance(obj, list):
        yield from (r for r in obj if isinstance(r, dict))
        return
    if not isinstance(obj, dict):
        return
    for k in ARRAY_KEYS:
        v = obj.get(k)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            yield from (r for r in v if isinstance(r, dict))
            return


def scan_references() -> dict[str, list[str]]:
    """返回 {数据文件相对路径: 排序去重后的 SRC id 列表}。"""
    refs: dict[str, set[str]] = {}
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.json")):
            if p.name.startswith("_") or "report" in p.name:
                continue
            try:
                obj = load_json(p)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            used: set[str] = set()
            for r in iter_records(obj):
                sid = r.get("source_id")
                if isinstance(sid, str) and sid.startswith("SRC-"):
                    used.add(sid)
            if used:
                rel = str(p.relative_to(ROOT)).replace("\\", "/")
                refs[rel] = used
    return {k: sorted(v) for k, v in sorted(refs.items())}


def main() -> int:
    sources = load_json(SOURCE_TABLE)["sources"]
    by_id = {}
    triplet_to_id = {}
    dup_triplets = []
    for s in sources:
        sid = s["id"]
        triplet = (s["source_name"], s["source_url"], int(s["year"]))
        if triplet in triplet_to_id:
            dup_triplets.append(triplet)
        triplet_to_id[triplet] = sid
        by_id[sid] = {
            "source_name": s["source_name"],
            "source_url": s["source_url"],
            "year": int(s["year"]),
            "source_type": s.get("source_type"),
        }

    refs = scan_references()
    used_ids = sorted({sid for v in refs.values() for sid in v})
    missing = [sid for sid in used_ids if sid not in by_id]

    payload = {
        "meta": {
            "title": "source 逻辑 id ↔ source 表三要素 映射",
            "purpose": "让 ② 的 loader 把数据里的字符串 source_id（SRC-XXX）无损转成 source 表 int 行 id",
            "owner": "徐（③ 数据工程）",
            "generated_at": "2026-10-13",
            "background": "③ 产物用 SRC-XXX 作可读来源标识；source 表 id 为 int 自增主键。",
            "usage": (
                "② 读到数据行的 source_id='SRC-XXX' 时："
                "① 在本表 map 中取 (source_name, source_url, year)；"
                "② 调 source_guard.ensure_source() 取得 source.id；"
                "③ 写入事实表的 source_id 列。"
                "注意：数据行内联的 source_name/source_url 可能与映射表不同"
                "（如 school_major_score 行内 source_url 为空），**一律以本表为准**，"
                "否则会新建出多余 source 行、甚至因 url 为空被 require_source 拒绝。"
            ),
            "integrity": {
                "source_count": len(sources),
                "triplet_unique": len(triplet_to_id),
                "duplicate_triplets": dup_triplets,
                "referenced_id_count": len(used_ids),
                "referenced_not_in_table": missing,
            },
        },
        "map": by_id,
        "reverse_triplet_to_id": {
            f"{n}|{u}|{y}": sid for (n, u, y), sid in sorted(triplet_to_id.items())
        },
        "referenced_by": refs,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUT_DIR / "source-id-map.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    out_csv = OUT_DIR / "source-id-map.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["src_id", "source_name", "source_url", "year", "source_type"])
        for sid in sorted(by_id):
            m = by_id[sid]
            w.writerow([sid, m["source_name"], m["source_url"], m["year"], m["source_type"]])

    print(f"source 共 {len(sources)} 条；三元组唯一数 {len(triplet_to_id)}")
    print(f"数据产物引用到的 SRC id：{len(used_ids)} 个")
    if missing:
        print(f"  ⛔ 引用但不在册：{missing}")
    else:
        print("  ✅ 全部在册")
    print(f"已写出：{out_json.relative_to(ROOT)}")
    print(f"已写出：{out_csv.relative_to(ROOT)}")
    return 1 if (dup_triplets or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())

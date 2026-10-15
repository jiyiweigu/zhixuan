#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回填 school.is_985 / is_211 / dual_class（院校层次标记）。

背景
  队长数据整合期在合并数据集里补齐了层次标记（52/135/171 行），
  但合并数据本体不入仓库。本脚本把同一口径直接落到 SQLite：

  来源 A：教育部 985/211/双一流 名单（data/dictionaries/school_tiers.json，
           含 aka 别名展开与 inherit.map 分校区/直属医学院白名单继承）
  来源 B：徐的软科榜 tags（data/schools/shanghai_top300_inhenan.json，交叉校验）

  口径与断言完全对齐 data/scripts/merge_datasets.py：
  - 985 ⊂ 211 ⊂ 双一流（兜底一致）
  - 河南 985 = 0；河南 211 全部属郑州大学（含中外合作办学等单列招生单位）
  - 独立学院（inherit.known_not_inherited）刻意不继承

用法
  python data/scripts/backfill_school_tiers.py            # 回填 + 校验
  python data/scripts/backfill_school_tiers.py --dry-run  # 只统计不写库
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / ".runtime" / "zhixuan.db"
TIERS_PATH = ROOT / "data" / "dictionaries" / "school_tiers.json"
SANE_PATH = ROOT / "data" / "schools" / "shanghai_top300_inhenan.json"


def _norm_name(value: str) -> str:
    s = re.sub(r"[\s　]+", "", str(value or ""))
    return re.sub(r"[（(].*?[)）]", "", s)


def _norm_full(value: str) -> str:
    s = re.sub(r"[\s　]+", "", str(value or ""))
    return s.replace("（", "(").replace("）", ")")


def _norm_base(value: str) -> str:
    return re.sub(r"\(.*?\)", "", _norm_full(value))


def _tier_index(doc: dict) -> dict[str, set[str]]:
    aka = doc.get("aka") or {}
    bidir: dict[str, set[str]] = {}
    for primary, alts in aka.items():
        for a in alts:
            bidir.setdefault(primary, set()).add(a)
            bidir.setdefault(a, set()).add(primary)

    def keys(name: str) -> set[str]:
        return {k for k in (_norm_full(name), _norm_base(name)) if k}

    idx: dict[str, set[str]] = defaultdict(set)
    for tier, flag in (("985", "is_985"), ("211", "is_211"), ("dual_class", "dual_class")):
        for name in doc.get(tier) or []:
            all_keys = keys(name)
            for alt in bidir.get(name, ()):
                all_keys |= keys(alt)
            for k in all_keys:
                idx[k].add(flag)
    return idx


def _tier_flags(idx, name, inherit=None):
    got = {"is_985": False, "is_211": False, "dual_class": ""}
    marks: set[str] = set()
    for k in (_norm_full(name), _norm_base(name)):
        marks |= idx.get(k, set())
    if not marks and inherit and name in inherit:
        parent = inherit[name]
        for k in (_norm_full(parent), _norm_base(parent)):
            marks |= idx.get(k, set())
    if "is_985" in marks:
        got["is_985"] = True
        got["is_211"] = True
    elif "is_211" in marks:
        got["is_211"] = True
    if "dual_class" in marks:
        got["dual_class"] = "双一流"
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    doc = json.loads(TIERS_PATH.read_text(encoding="utf-8"))
    tiers = _tier_index(doc)
    inherit_map = (doc.get("inherit") or {}).get("map") or {}

    sane: dict[str, dict] = {}
    if SANE_PATH.exists():
        for x in json.loads(SANE_PATH.read_text(encoding="utf-8"))["records"]:
            tags = set(x.get("tags") or [])
            item = {"tags": tags, "name": x.get("name")}
            if x.get("hn_code"):
                sane.setdefault("code:" + str(x["hn_code"]), item)
            sane.setdefault("name:" + _norm_base(x.get("hn_name") or x.get("name")), item)

    db = sqlite3.connect(DB)
    rows = db.execute("SELECT id, name, code, province FROM school").fetchall()
    print(f"school 共 {len(rows)} 行")

    updates = []
    src_count = {"教育部名单": 0, "软科榜": 0}
    for sid, name, code, province in rows:
        flags = _tier_flags(tiers, name or "", inherit_map)
        from_a = any(flags.values())
        s = sane.get("code:" + str(code)) or sane.get("name:" + _norm_base(name or ""))
        from_b = False
        if s:
            if "985" in s["tags"]:
                flags["is_985"] = flags["is_211"] = True
                from_b = True
            elif "211" in s["tags"]:
                flags["is_211"] = True
                from_b = True
            if "双一流" in s["tags"] and not flags["dual_class"]:
                flags["dual_class"] = "双一流"
                from_b = True
        if from_a:
            src_count["教育部名单"] += 1
        if from_b:
            src_count["软科榜"] += 1
        updates.append((int(flags["is_985"]), int(flags["is_211"]),
                        flags["dual_class"], sid))

    n985 = sum(1 for u in updates if u[0])
    n211 = sum(1 for u in updates if u[1])
    ndual = sum(1 for u in updates if u[2])
    print(f"标记结果：is_985={n985}、is_211={n211}、dual_class={ndual}（队长口径 52/135/171）")
    print(f"来源贡献：{src_count}")

    # 交叉验证（与 merge_datasets.py 同口径）
    flag_by_id = {u[3]: u for u in updates}
    henan = [(sid, name) for sid, name, code, prov in rows if prov == "河南"]
    hn_985 = sorted({_norm_name(n) for sid, n in henan if flag_by_id[sid][0]})
    hn_211 = sorted({_norm_name(n) for sid, n in henan if flag_by_id[sid][1]})
    assert not hn_985, f"河南无 985，实际 {hn_985}"
    assert hn_211 and all("郑州大学" in n for n in hn_211), f"河南 211 异常 {hn_211}"
    assert all(u[1] for u in updates if u[0]), "存在 is_985 但非 is_211"
    assert all(u[2] for u in updates if u[1]), "存在 is_211 但非双一流"
    print("交叉验证通过：河南 985=0、211 全属郑大、985⊂211⊂双一流")

    if args.dry_run:
        print("dry-run，未写库")
        return 0
    db.executemany("UPDATE school SET is_985=?, is_211=?, dual_class=? WHERE id=?", updates)
    db.commit()
    print(f"已写库 {len(updates)} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())

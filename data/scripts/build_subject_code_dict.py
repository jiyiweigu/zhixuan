# -*- coding: utf-8 -*-
"""
构建选考科目要求代码字典（`second_require`）
============================================

背景
====
张分支 `subject_requirement.json` 用**平台内部编码** `second_require` 表示「再选科目」
（如 `70001` / `70008`），我方契约里没有该码位。若将来接入，须先有对照表。

★ 编码含义的来源（**不是猜的**）
张的记录同时带了**人类可读文本** `subject_req`（如「首选物理，再选化学」）。
本脚本按 `second_require` 分组，统计其对应的「再选」文本片段；
**仅当分组内文本 100% 唯一时**才写入字典，否则标记为待人工核实 —— 严格遵守「严禁编数据」。

数据源（仓库外，须先导出）：
  git archive origin/feature/zhang data/output data/jiangxi/output \\
    | tar -x -C "C:/Users/lenovo/.pg16/zhang_data"

用法
====
  python data/scripts/build_subject_code_dict.py
  python data/scripts/build_subject_code_dict.py --zhang "C:/Users/lenovo/.pg16/zhang_data"
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "dictionaries" / "subject-require-codes.json"
DEFAULT_ZHANG = Path("C:/Users/lenovo/.pg16/zhang_data")
SRC_REL = "data/jiangxi/output/subject_requirement.json"

# 已知的单科码 → 科目（由第二通道文本实证，见 subject_req）
SINGLE_HINT = {"70001": "化学", "70002": "生物", "70003": "思想政治", "70005": "地理"}


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 second_require 代码字典")
    ap.add_argument("--zhang", default=str(DEFAULT_ZHANG))
    args = ap.parse_args()

    src = Path(args.zhang) / SRC_REL
    if not src.exists():
        print(f"❌ 未找到张分支文件：{src}（先 git archive 导出）")
        return 1
    recs = json.loads(src.read_text(encoding="utf-8"))
    print(f"读取 {src} —— {len(recs)} 条")

    grouped: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in recs:
        sr = r.get("subject_req") or ""
        m = re.search(r"再选(.+)$", sr)
        tail = m.group(1).strip() if m else ""
        grouped[str(r.get("second_require")).strip()][tail] += 1

    codes, unresolved = [], []
    for code in sorted(grouped, key=lambda c: -sum(grouped[c].values())):
        cnt = grouped[code]
        total = sum(cnt.values())
        if len(cnt) == 1:                       # 文本唯一 ⇒ 可确定
            meaning = next(iter(cnt))
            items = [c.strip() for c in code.split(",") if c.strip()]
            codes.append({
                "code": code,
                "meaning": meaning,
                "kind": "single" if len(items) == 1 else "combination",
                "members": [SINGLE_HINT.get(i, f"未知({i})") for i in items],
                "is_unlimited": meaning == "不限",
                "sample_count": total,
                "evidence": f"subject_req 的『再选』段唯一取值：{meaning}",
            })
            print(f"  ✅ {code:<14} → {meaning}（{total} 条）")
        else:                                    # 文本不唯一 ⇒ 不猜
            unresolved.append({"code": code, "texts": dict(cnt), "sample_count": total})
            print(f"  ⚠ {code:<14} → 文本不唯一，留待人工：{dict(cnt)}")

    out = {
        "meta": {
            "title": "选考科目要求代码字典（second_require）",
            "generated_at": "2026-10-14",
            "owner": "徐（③ 数据工程）",
            "scope": "解析张分支 subject_requirement 的 second_require 编码；我方契约无此码位",
            "method": "按 second_require 分组统计 subject_req 的『再选』文本；仅唯一取值才收录",
            "source": "origin/feature/zhang · " + SRC_REL,
            "source_records": len(recs),
            "rule": "严禁猜测：文本不唯一一律进 unresolved，不写入 codes",
            "note": "该编码为采集平台（掌上高考）内部编码，非国家/考试院官方码；接入前须队长确认可用性",
        },
        "codes": codes,
        "unresolved": unresolved,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n写入 {OUT.relative_to(ROOT).as_posix()}：确定 {len(codes)} 个码，待核 {len(unresolved)} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())

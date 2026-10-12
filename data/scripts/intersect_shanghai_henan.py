# -*- coding: utf-8 -*-
"""
软科 top300 ∩ 在豫招生本科院校 —— 交叉脚本
=========================================
输入：
  data/schools/shanghai_top300.json        软科 2024 主榜前 300
  data/schools/schools_merged.json         在豫招生本科院校库 1367 所（任务 2.1 产物）

匹配策略（逐级降级）：
  1. 校名全等
  2. 去括号后全等（处理「XX大学(XX校区)」）
  3. 去「大学/学院/职业技术/职业」后全等（宽容简称）

输出：
  data/schools/shanghai_top300_inhenan.json   交集明细（含软科排名 + 河南库字段）
  data/schools/软科top300_在豫招生_对照报告.md  人读报告

⚠️ 未命中 ≠ 数据缺失。软科榜含部分不在河南投放本科计划的院校（如湖州师范学院、
   绍兴文理学院等，主要面向本省招生），属正常口径差异，不做补全、不打标记。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCH = BASE_DIR / "schools"

SRK = SCH / "shanghai_top300.json"
HENAN = SCH / "schools_merged.json"
OUT_JSON = SCH / "shanghai_top300_inhenan.json"


def norm(s: str) -> str:
    s = re.sub(r"[（(].*?[)）]", "", s or "")
    for w in ("职业技术", "职业", "大学", "学院"):
        s = s.replace(w, "")
    return s.strip()


def main() -> int:
    srk = json.loads(SRK.read_text(encoding="utf-8"))["rankings"]
    henan = json.loads(HENAN.read_text(encoding="utf-8"))["records"]

    h_full = {r["name"]: r for r in henan}
    h_norm: dict[str, dict] = {}
    for r in henan:
        h_norm.setdefault(norm(r["name"]), r)

    hit, miss = [], []
    for r in srk:
        m = h_full.get(r["name"]) or h_norm.get(norm(r["name"]))
        if m:
            hit.append({
                **r,
                "hn_name": m["name"],
                "hn_code": m.get("code"),
                "hn_ownership": m.get("ownership"),
                "hn_city": m.get("city"),
            })
        else:
            miss.append(r)

    OUT_JSON.write_text(json.dumps({
        "meta": {
            "desc": "软科 2024 主榜 top300 ∩ 在豫招生本科院校",
            "srk_count": len(srk),
            "henan_count": len(henan),
            "intersect": len(hit),
            "missing": len(miss),
            "source_name": "上海软科教育信息咨询有限公司",
            "source_url": "https://www.shanghairanking.cn/rankings/bcur/2024",
            "year": 2024,
            "note": "第三方机构排名，非官方数据",
        },
        "records": hit,
        "not_in_henan": miss,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 统计
    c985 = sum(1 for r in hit if "985" in r["tags"])
    c211 = sum(1 for r in hit if "211" in r["tags"])
    csyl = sum(1 for r in hit if "双一流" in r["tags"])
    prov = Counter(r["province"] for r in hit)

    print(f"[intersect] 软科top300={len(srk)}  在豫本科={len(henan)}")
    print(f"            命中={len(hit)}  未命中={len(miss)}")
    print(f"            985={c985}  211={c211}  双一流={csyl}")
    print(f"            河南本省={prov.get('河南', 0)}")
    print(f"[out] {OUT_JSON}")

    # 报告
    report = SCH / "软科top300_在豫招生_对照报告.md"
    lines = [
        "# 软科 top300 ∩ 在豫招生本科院校（2024）",
        "",
        "> **数据性质**：软科中国大学排名由**上海软科教育信息咨询有限公司**（第三方机构）发布，",
        "> **非官方数据**。本项目仅用作「参考位次 / 层次校验」辅助，不替代官方来源。",
        "> 来源：<https://www.shanghairanking.cn/rankings/bcur/2024> ｜ year=2024",
        "",
        "## 一、口径",
        "",
        "| 项 | 数量 |",
        "|---|---:|",
        f"| 软科 2024 主榜 top300 | {len(srk)} |",
        f"| 在豫招生本科院校（任务 2.1） | {len(henan)} |",
        f"| **两者交集** | **{len(hit)}** |",
        f"| 在豫无本科计划的 top300 | {len(miss)} |",
        "",
        f"交集内：985 **{c985}** 所 ｜ 211 **{c211}** 所 ｜ 双一流 **{csyl}** 所。",
        "",
        "## 二、未命中清单（在豫无本科招生计划）",
        "",
        "| 软科排名 | 校名 | 省份 |",
        "|---:|---|---|",
    ]
    for r in miss:
        lines.append(f"| {r['ranking']} | {r['name']} | {r['province']} |")
    lines += [
        "",
        "> 未命中**不是数据缺失**，而是这些院校不在河南投放本科招生计划（多面向本省），",
        "> 属正常口径差异。**不做补全、不臆造**。",
        "",
        "## 三、交集内 top300 省份分布（前 15）",
        "",
        "| 省份 | 所数 |",
        "|---|---:|",
    ]
    for p, n in prov.most_common(15):
        lines.append(f"| {p} | {n} |")
    lines += [
        "",
        f"> 河南本省院校进入软科 top300 的有 **{prov.get('河南', 0)}** 所。",
        "",
        "## 四、交集明细（前 60，完整见 JSON）",
        "",
        "| 软科排名 | 校名 | 省份 | 类别 | 得分 | 标签 | 办学性质 |",
        "|---:|---|---|---|---:|---|---|",
    ]
    for r in hit[:60]:
        lines.append(
            f"| {r['ranking']} | {r['name']} | {r['province']} | {r['category']} | "
            f"{r['score']} | {'/'.join(r['tags']) or '—'} | {r['hn_ownership'] or '—'} |"
        )
    lines += ["", f"> 完整 {len(hit)} 条见 `shanghai_top300_inhenan.json`。", ""]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"[out] {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

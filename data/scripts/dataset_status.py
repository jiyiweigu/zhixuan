#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""③ 数据集核实登记表 —— 把「核实状态」与契约 `data_status` 拆开（唯一口径源）

## 为什么需要这张表

契约 v1.3 的 `data_status` 只有四值
`available | partial | schema_only | unavailable`，
且**明确禁用** `verified` / `pending` / `mock`
（见 `docs/api-contract.md` L41 / L345 / L528）。
这四值描述的是**数据完备度**，不是「是否核实过」。

而 ③ 内部长期用 `verified` / `pending` 描述**核实进度**。两者混用造成三个实际后果：

1. 生成脚本仍写 `data_status: "pending"`（`import_score_segment.py` /
   `fetch_schools.py`）与 `"verified"`（`parse_major_catalog.py`）——
   属废弃枚举，**重新生成即回归**，`validate.py` 必报 ERROR；
2. 已入库的数据被标成 `schema_only`（契约含义是「结构就绪、**数据尚未导入**」），
   界面会误标「规划中」，**低报**了实际可用数据；
3. 核实成果无处落账 —— `score_segment` 表**没有** `data_status` 列，
   `rule_dataset_status.dataset` 枚举也**不含** `score_segment`
   （只含 5 个规则集），所以核实结论落不进库。

本表把两个维度拆开：

* `data_status` —— 契约四值，写入产物、**出接口**；
* `verification_status` —— `verified | unverified | partial`，**只登记在本表、不出接口**。

## 口径（③ 定，N31 待队长追认）

| 情形 | `data_status` | `verification_status` |
|---|---|---|
| 已入库 + 通过 L2 核实（E3） | `available` | `verified` |
| 已入库 + 未做第二通道核实 | `partial` | `unverified` |
| 已入库 + 部分可信（如 OCR 缺口） | `partial` | `partial` |
| 结构就绪、数据未导入 | `schema_only` | `unverified` |
| 无匹配数据版本 | `unavailable` | `unverified` |

一句话：**已入库 ⇒ 至少 `partial`；通过核实 ⇒ `available`。**
一分一段 10 份产物均已入库，故**不再使用 `schema_only`**。

## 载体说明

`data/score_segment/score_segment_*.json` 属「数据本体出仓」清单（`.gitignore`），
**不入库**，可经 `data/DOWNLOAD.md` 重建。故权威口径必须落在**受版本管理**的
本表（`data/dictionaries/dataset-verification.json`），产物内的 `data_status`
由 `apply` 按本表写入、可随时重建。

## 用法

    python data/scripts/dataset_status.py gen     # 生成/刷新登记表
    python data/scripts/dataset_status.py apply   # 按登记表写回产物（记录级 + meta 级）
    python data/scripts/dataset_status.py check   # 校验产物与登记表一致（不一致退出码 2）
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEG_DIR = ROOT / "data" / "score_segment"
REGISTRY = ROOT / "data" / "dictionaries" / "dataset-verification.json"

DATA_STATUS_ENUM = ["available", "partial", "schema_only", "unavailable"]
VERIFICATION_ENUM = ["verified", "unverified", "partial"]
FORBIDDEN_DATA_STATUS = ["verified", "pending", "mock"]  # 契约 v1.3 禁用，见 L41

PROVINCE_CODE = {"河南": "41", "江西": "36"}

# ---------------------------------------------------------------------- #
# E3 核实证据（2026-10-14 实测，来源 data/E3_试点核实报告_徐.md）
#   channel_a：张分支第二采集线逐条交叉验证（张 = 平行数据工程线）
#   channel_b：vs gaokao.eol.cn 官方转载页全量逐行（我校实的本体）
# ---------------------------------------------------------------------- #
E3_EVIDENCE: dict[tuple[str, int], dict] = {
    ("河南", 2023): {
        "channel_a": {"desc": "张分支第二采集线逐条交叉验证",
                      "consistent": 1193, "mismatch": 0, "counterpart_only": 1,
                      "note": "张多 1 条 (文科,680)。官方转载页该处为 "
                              "685-750/10/10 → 681/5/15 → 679/4/19，**无 680 行**，"
                              "系张方解析生成物；我方未漏采、不补。"},
        "channel_b": {"desc": "vs gaokao.eol.cn 官方转载页全量逐行",
                      "consistent": 1193, "mismatch": 0, "official_only": 0},
        "urls": {"文科": "https://gaokao.eol.cn/he_nan/dongtai/202306/t20230625_2446851.shtml",
                 "理科": "https://gaokao.eol.cn/he_nan/dongtai/202306/t20230625_2446847.shtml"},
        "official_source_note": "页面署名「河南省教育厅」，但页脚声明版权属中国教育在线",
    },
    ("河南", 2024): {
        "channel_a": {"desc": "张分支第二采集线逐条交叉验证",
                      "consistent": 1182, "mismatch": 0, "counterpart_only": 0},
        "channel_b": {"desc": "vs gaokao.eol.cn 官方转载页全量逐行",
                      "consistent": 1182, "mismatch": 0, "official_only": 0},
        "urls": {"文科": "https://gaokao.eol.cn/he_nan/dongtai/202406/t20240625_2619212.shtml",
                 "理科": "https://gaokao.eol.cn/he_nan/dongtai/202406/t20240625_2619212_1.shtml"},
        "official_source_note": "页面署名「河南考试院」",
    },
    ("河南", 2025): {
        "channel_a": {"desc": "张分支第二采集线逐条交叉验证",
                      "consistent": 1198, "mismatch": 0, "counterpart_only": 0},
        "channel_b": {"desc": "vs gaokao.eol.cn 官方转载页全量逐行",
                      "consistent": 1198, "mismatch": 0, "official_only": 0},
        "urls": {"历史类": "https://gaokao.eol.cn/he_nan/dongtai/202506/t20250625_2676858.shtml",
                 "物理类": "https://gaokao.eol.cn/he_nan/dongtai/202506/t20250625_2676859.shtml"},
        "official_source_note": "页面署名「河南省教育考试院」；官方表不分批次，"
                                "批次线以批注形式给出（185/471/552 历史、185/427/535 物理）",
    },
    ("江西", 2024): {
        "channel_a": {"desc": "张分支第二采集线逐条交叉验证",
                      "consistent": 1148, "mismatch": 0, "counterpart_only": 0},
        "channel_b": {"desc": "vs gaokao.eol.cn 官方转载页全量逐行",
                      "consistent": 1146, "mismatch": 0, "official_only": 0,
                      "zero_row_count": 2,
                      "note": "官方表缺 历史类 103 / 物理类 114 两行（该分无考生，官方不列）；"
                              "我方保留，与官方相邻行数值完全自洽 ⇒ 我方更完整，非错误。"},
        "urls": {"历史类": "https://gaokao.eol.cn/jiang_xi/dongtai/202406/t20240626_2619467.shtml",
                 "物理类": "https://gaokao.eol.cn/jiang_xi/dongtai/202406/t20240626_2619478.shtml"},
        "official_source_note": "页面署名「江西省教育厅」；官方批注行给出批次线 "
                                "463/532（历史）、448/520（物理）",
    },
}

# 未核实（无第二通道）→ 补核路径登记，见 data/E3_试点核实报告_徐.md §七
RECHECK_PATH = ("补核路径：① 按 gaokao.eol.cn 站内同栏目检索对应年份页面，逐一核内容；"
                "② 或人工下载省考试院 PDF。两路均须人工确认，不自动采信。")


def _rel(p: Path) -> str:
    """相对仓库根的 posix 风格路径（规避跨盘 relpath 抛 ValueError）。"""
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def load_products() -> list[tuple[Path, dict]]:
    out: list[tuple[Path, dict]] = []
    for p in sorted(glob.glob(str(SEG_DIR / "score_segment_20*.json"))):
        fp = Path(p)
        with fp.open("r", encoding="utf-8") as fh:
            out.append((fp, json.load(fh)))
    return out


def is_ocr(meta: dict) -> bool:
    return "review_status" in meta or str(meta.get("parse_method", "")).startswith("扫描件 OCR")


def build_entries() -> list[dict]:
    """依据产物实际内容 + 内置 E3 证据，生成登记项。"""
    entries: list[dict] = []
    for fp, d in load_products():
        meta = d.get("meta") or {}
        segs = d.get("segments") or []
        prov, year = meta.get("province"), int(meta.get("year"))
        subs = sorted({r.get("subject_type") for r in segs if r.get("subject_type")})
        src_ids = sorted({r.get("source_id") for r in segs if r.get("source_id")}) or [meta.get("source_id")]

        ent: dict = {
            "dataset": "score_segment",
            "file": _rel(fp),
            "province": prov,
            "province_code": PROVINCE_CODE.get(prov, ""),
            "year": year,
            "subject_type": meta.get("subject_type"),      # 单科类文件才有；否则 null
            "subject_types": subs,
            "rows": len(segs),
            "source_id": src_ids[0] if len(src_ids) == 1 else src_ids,
            "checked_at": "2026-10-14",
        }

        ev = E3_EVIDENCE.get((prov, year))
        if ev is not None:
            ent["data_status"] = "available"
            ent["verification_status"] = "verified"
            ent["evidence"] = ev
            a, b = ev["channel_a"], ev["channel_b"]
            ent["verification_note"] = (
                f"已核实（E3 · {ent['checked_at']}）：通道A（张分支第二采集线）一致 "
                f"{a['consistent']}、不一致 {a['mismatch']}；通道B（gaokao.eol.cn 官方转载页"
                f"逐行）一致 {b['consistent']}、不一致 {b['mismatch']}、仅官方 "
                f"{b.get('official_only', 0)}。出处：data/E3_试点核实报告_徐.md"
            )
        elif is_ocr(meta):
            ent["data_status"] = "partial"
            ent["verification_status"] = "partial"
            ent["evidence"] = {
                "parse_method": meta.get("parse_method"),
                "final_rows": meta.get("final_rows"),
                "high_confidence_rows": meta.get("high_confidence_rows"),
                "interpolated_rows": meta.get("interpolated_rows"),
                "gap_count": len(meta.get("gap_scores") or []),
                "source_url": meta.get("source_url"),
            }
            ent["verification_note"] = (
                f"OCR 产物：{meta.get('high_confidence_rows')} 高置信 / "
                f"{meta.get('interpolated_rows')} 插值 / "
                f"{len(meta.get('gap_scores') or [])} 个分数无可靠值待人工补录；"
                f"来源为省考试院官方扫描件，但逐条数值未经第二通道核实 ⇒ partial。"
                f"{meta.get('review_status') or ''}"
            )
        else:
            ent["data_status"] = "partial"
            ent["verification_status"] = "unverified"
            ent["evidence"] = {"channels": ["无第二采集线", "官方页未取得"], "rows": len(segs)}
            ent["verification_note"] = (
                f"已入库但未做第二通道核实（{len(segs)} 条）⇒ partial。{RECHECK_PATH}"
            )
        entries.append(ent)
    return entries


def cmd_gen(_args) -> int:
    entries = build_entries()
    doc = {
        "meta": {
            "owner": "徐（③ 数据工程）",
            "purpose": "③ 数据集核实登记表（唯一口径源）：把「核实状态」与契约 data_status 分开登记。"
                       "产物内 data_status 由本表 apply 写入、可随时重建。",
            "updated_at": "2026-10-14",
            "data_status_enum": DATA_STATUS_ENUM,
            "verification_enum": VERIFICATION_ENUM,
            "forbidden_data_status": FORBIDDEN_DATA_STATUS,
            "mapping_rule": "已入库 ⇒ 至少 partial；通过 L2 核实 ⇒ available；"
                            "结构就绪未导入 ⇒ schema_only；无版本 ⇒ unavailable。",
            "contract_ref": "docs/api-contract.md L41 / L345 / L528",
            "carrier_note": "data/score_segment/score_segment_*.json 属「数据本体出仓」"
                            "（.gitignore，不入库）；故权威口径落在本表。",
            "regen": "python data/scripts/dataset_status.py gen | apply | check",
        },
        "entries": entries,
    }
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✓ 登记表已写入 {_rel(REGISTRY)}（{len(entries)} 项）\n")
    print(f"{'文件':<34}{'省':<6}{'年':<6}{'行数':>6}  {'data_status':<11}{'verification'}")
    print("-" * 82)
    for e in entries:
        print(f"{Path(e['file']).name:<34}{e['province']:<6}{e['year']:<6}{e['rows']:>6}  "
              f"{e['data_status']:<11}{e['verification_status']}")
    from collections import Counter
    ca = Counter(e["data_status"] for e in entries)
    cv = Counter(e["verification_status"] for e in entries)
    print("-" * 82)
    print(f"合计 {sum(e['rows'] for e in entries):,} 行 ｜ data_status={dict(ca)} ｜ "
          f"verification={dict(cv)}")
    return 0


def _load_registry() -> dict:
    if not REGISTRY.exists():
        print(f"✗ 登记表不存在：{_rel(REGISTRY)}；先跑 gen", file=sys.stderr)
        sys.exit(3)
    with REGISTRY.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def cmd_apply(_args) -> int:
    doc = _load_registry()
    changed_val = 0
    touched_files = 0
    for e in doc["entries"]:
        fp = ROOT / e["file"]
        if not fp.exists():
            print(f"✗ 产物缺失：{e['file']}", file=sys.stderr)
            return 4
        with fp.open("r", encoding="utf-8") as fh:
            d = json.load(fh)
        meta = d.setdefault("meta", {})
        before = meta.get("data_status")
        meta["data_status"] = e["data_status"]
        meta["verified_note"] = e["verification_note"]
        for r in d.get("segments", []):
            if r.get("data_status") != e["data_status"]:
                changed_val += 1
            r["data_status"] = e["data_status"]
        fp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        touched_files += 1
        flag = "" if before == e["data_status"] else f"  (meta: {before} → {e['data_status']})"
        print(f"  ✓ {Path(e['file']).name:<34}{e['data_status']:<11}{e['rows']:>6} 行{flag}")
    print(f"\n✓ 写回 {touched_files} 份产物，记录级改动 {changed_val} 条")
    return 0


def cmd_check(_args) -> int:
    doc = _load_registry()
    bad = 0
    forbidden = 0
    for e in doc["entries"]:
        fp = ROOT / e["file"]
        if not fp.exists():
            print(f"✗ 产物缺失：{e['file']}", file=sys.stderr)
            return 4
        with fp.open("r", encoding="utf-8") as fh:
            d = json.load(fh)
        meta_status = (d.get("meta") or {}).get("data_status")
        if meta_status != e["data_status"]:
            print(f"✗ {Path(e['file']).name} meta.data_status={meta_status!r} "
                  f"≠ 登记表 {e['data_status']!r}")
            bad += 1
        for r in d.get("segments", []):
            s = r.get("data_status")
            if s != e["data_status"]:
                bad += 1
                if bad <= 5:
                    print(f"✗ {Path(e['file']).name} 记录 data_status={s!r} "
                          f"≠ 登记表 {e['data_status']!r}（score={r.get('score')}）")
                continue
            if s in FORBIDDEN_DATA_STATUS:
                forbidden += 1
    if forbidden:
        print(f"✗ 发现 {forbidden} 处契约禁用枚举（{FORBIDDEN_DATA_STATUS}）")
    if bad or forbidden:
        print(f"\n✗ 不一致 {bad} 处 —— 跑 `dataset_status.py apply` 修正")
        return 2
    total = sum(e["rows"] for e in doc["entries"])
    print(f"✓ {len(doc['entries'])} 份产物 / {total:,} 条记录与登记表一致，"
          f"无契约禁用枚举（{FORBIDDEN_DATA_STATUS}）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="③ 数据集核实登记表（gen / apply / check）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen", help="生成/刷新登记表").set_defaults(func=cmd_gen)
    sub.add_parser("apply", help="按登记表写回产物").set_defaults(func=cmd_apply)
    sub.add_parser("check", help="校验产物与登记表一致").set_defaults(func=cmd_check)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

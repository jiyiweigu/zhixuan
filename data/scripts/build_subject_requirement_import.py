# -*- coding: utf-8 -*-
"""
选科要求 → 管理端规则导入包转换脚本
====================================
把 parse_subject_req.py --scan 产出的 `subject-requirement.json` 转成
契约 8.8 `POST /api/admin/rule-datasets/import`（dataset=subject_requirement，
单次 ≤500、整批事务）可直接投喂的导入包。

⚠️ 不手改产出的数据文件 —— 本脚本只做格式对齐（任务 04 第 4 条）。

背景（为什么管理端没有 RULE_DATASETS 注册表）：
  `backend/app/services/rule_admin.py` 的实际注册机制是
  `_IMPORT_BUILDERS[DATASET_SUBJECT_REQUIREMENT] = "subject_requirement"`，
  数据集标识 `subject_requirement` 已在 `app/models/constants.py` 注册，
  管理端规则页（契约 §8.8）可直接通过导入接口写入 —— 无需改后端。

转换规则：
  1. 输入优先取完整版 `data/raw/subject-requirement.full.json`；
     不存在时退回仓库内 `data/dictionaries/subject-requirement.json`（样本）。
  2. **只导 status=ok 且 target_type=group 的行**：
     - missing 不是规则（契约：缺失≠不限），不导；
     - unparsed 未经人工复核，导进去等于猜规则（红线），不导；
     - target_type=major（组内取值不一致的 102 行）在 SubjectRequirement 表
       里无 major_code 列、major_id 首期恒空，直接导入会丢失专业身份 ——
       输出到 `data/staged/subject-requirement-major-pending.json` 待专业库
       挂载 major_id 后经管理端录入，**不猜**。
  3. 按 (province, year) 分组再切 500 条/包，顶层 province_code/year 与
     recompute_dataset_status 的键保持一致。
  4. 来源三要素统一填 SRC-GAOKAO-COMPASS（渠道登记，与 source-table.json 一致；
     作品内事实结论的 source_url 须指向省考试院/阳光高考 —— 合规红线）。

产出：`data/staged/subject-requirement-import/`（中间层，不入库）
  part-<省码>-<年>-<序号>.json        → 导入请求体（curl/管理端直投）
  subject-requirement-major-pending.json → 专业级行待办
  manifest.json                      → 汇总

用法：
  python build_subject_requirement_import.py            # 生成导入包
  python build_subject_requirement_import.py --dry-run  # 只打印统计
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # data/
FULL_PATH = BASE_DIR / "raw" / "subject-requirement.full.json"
REPO_PATH = BASE_DIR / "dictionaries" / "subject-requirement.json"
STAGED_DIR = BASE_DIR / "staged" / "subject-requirement-import"

SOURCE_NAME = "Gaokao-Compass-11M 高考数据集（MIT，DOI 10.57967/hf/9882）"
SOURCE_URL = "https://hf-mirror.com/datasets/choucsan/Gaokao-Compass-11M"
DATASET = "subject_requirement"
CHUNK = 500                                                # 契约 8.8 单次上限


def load_rows() -> tuple[list[dict], str]:
    path = FULL_PATH if FULL_PATH.exists() else REPO_PATH
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc.get("rows", []), str(path)


def to_item(row: dict) -> dict:
    return {
        "province_code": row.get("province_code") or "",
        "province": row.get("province") or "",
        "year": row.get("year"),
        "batch": row.get("batch") or "",
        "school_id": row.get("school_id"),
        "group_code": row.get("group_code") or "",
        "major_id": None,                      # 首期恒空，与 school_major_score 同口径
        "first_subject": row.get("first_subject"),          # null = 不限首选
        "secondary_subjects": list(row.get("secondary_subjects") or []),
        "logic": row.get("logic") or "all",
        "source_name": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "source_year": row.get("year"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows, src = load_rows()
    print(f"[in ] {src}（{len(rows)} 行）")

    groups, pending = [], []
    stat = Counter()
    for r in rows:
        stat[r.get("status")] += 1
        if r.get("status") != "ok":
            continue                      # missing / unparsed 不导（见文件头说明）
        if r.get("target_type") == "group":
            groups.append(r)
        else:
            pending.append(r)

    # school_id 未挂载的组级行也无法被引擎按院校使用 → 与 pending 同理登记
    groups_ok, pending_no_school = [], []
    for r in groups:
        (groups_ok if r.get("school_id") else pending_no_school).append(r)

    print(f"[cut] status: {dict(stat)}")
    print(f"[cut] 组级可导入 {len(groups_ok)}（school_id 已挂载）")
    print(f"[cut] 专业级待办 {len(pending)}（组内取值不一致，需 major_id 挂载）")
    print(f"[cut] 组级待办 {len(pending_no_school)}（school_id 未挂载，宁缺不猜）")

    if args.dry_run:
        return 0

    STAGED_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 按 (province, year) 分组切包 ----
    by_key: dict[tuple, list[dict]] = {}
    for r in groups_ok:
        by_key.setdefault((r["province"], r["year"]), []).append(r)

    parts = []
    for (prov, year), items in sorted(by_key.items()):
        code = items[0].get("province_code") or ""
        for i in range(0, len(items), CHUNK):
            chunk = items[i:i + CHUNK]
            payload = {
                "dataset": DATASET,
                "province_code": code,
                "province": prov,
                "year": year,
                "batch_code": "",
                "exam_type": "normal",
                "items": [to_item(x) for x in chunk],
            }
            p = STAGED_DIR / f"part-{code or prov}-{year}-{i // CHUNK + 1:03d}.json"
            p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            parts.append({"file": p.name, "province": prov, "year": year,
                          "items": len(chunk)})
            print(f"[out] {p.name}  {len(chunk)} 条")

    # ---- 待办（专业级 + 未挂载组级）----
    if pending or pending_no_school:
        pd = STAGED_DIR / "subject-requirement-major-pending.json"
        pd.write_text(json.dumps({
            "meta": {
                "title": "选科要求待办行（暂不可导入 subject_requirement 表）",
                "reason": [
                    "target_type=major：组内选科取值不一致，SubjectRequirement 表无 "
                    "major_code 列、major_id 首期恒空，直接导入会丢失专业身份；",
                    "school_id=null：上游校名挂不上 1367 所本科院校库（多为专科批院校），"
                    "宁缺不猜。",
                ],
                "next_step": "专业库 major_id 挂载后，经管理端（契约 §8.8）逐条录入；"
                             "引擎侧对无规则组一律返回 3001（绝不静默放行）。",
            },
            "major_level_rows": pending,
            "unmatched_group_rows": pending_no_school,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[out] {pd.name}  专业级 {len(pending)} + 未挂载组级 {len(pending_no_school)}")

    (STAGED_DIR / "manifest.json").write_text(json.dumps({
        "dataset": DATASET,
        "source_rows": len(rows),
        "importable": len(groups_ok),
        "pending": {"major_level": len(pending), "unmatched_group": len(pending_no_school)},
        "api": "POST /api/admin/rule-datasets/import（契约 8.8，单次 ≤500）",
        "parts": parts,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[out] manifest.json（共 {len(parts)} 包 / 可导入 {len(groups_ok)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

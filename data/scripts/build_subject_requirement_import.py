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

转换规则（补充）：
  5. **组级去重**：导入通道按 (province, year, school_id, group_code, 批次, 首选科目)
     逻辑键拒收重复，同键必须先在此消解 —— 内容一致（first/secondary/logic 全同）
     折叠保留首条；内容冲突全部排除并登记
     `subject-requirement-group-conflicts.json` 待人工复核
     （红线：宁可缺不可猜，引擎对无规则组返回 3001）。
  6. **同组多口径是合法的**：河南计划表按科类独立编组号（同一「校+组号」在历史类/
     物理类下是不同专业组），且组号在本科批/专科批间也可能重号 —— 这两类行
     按 批次+首选科目 各自成为独立规则行，不得跨科类/跨批次折叠。

产出：`data/staged/subject-requirement-import/`（中间层，不入库）
  part-<省码>-<年>-<序号>.json        → 导入请求体（curl/管理端直投）
  subject-requirement-major-pending.json → 专业级行待办
  subject-requirement-group-conflicts.json → 组级内容冲突行（未导入待复核）
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

# 批次展示名 → batch_code（与 backend/app/models/constants.BATCH_ALIAS_TO_CODE
# 保持同步；本脚本独立运行，不引后端依赖。未登记的展示名原样返回——
# 与 batch_code_of 行为一致，绝不静默落入默认值）。
_BATCH_ALIAS = {
    "本科批": "undergraduate_regular",
    "普通本科批": "undergraduate_regular",
    "本科批次": "undergraduate_regular",
    "本科": "undergraduate_regular",            # 江西招生计划口径
    "提前批": "undergraduate_early",
    "普通本科提前批": "undergraduate_early",
    "提前本科": "undergraduate_early",          # 江西招生计划口径
    "高职（专科）批": "vocational_regular",
    "高职（专科）批次": "vocational_regular",
    "高职(专科)": "vocational_regular",         # 江西招生计划口径（半角括号）
    "专科批": "vocational_regular",             # 河南招生计划口径
    "艺术类/体育类本科批次": "undergraduate_art_sport",
}


def _batch_code(batch: str) -> str:
    value = str(batch or "").strip()
    return "undergraduate_regular" if not value else _BATCH_ALIAS.get(value, value)


def _first_key(value) -> str:
    """首选科目归一：空 / 不限 → ''（无首选约束），其余原样（物理/历史）。"""
    text = str(value or "").strip()
    return "" if text in ("", "不限") else text


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

    # ---- 组级去重（导入通道按逻辑键拒收重复：同键必须先在此消解）----
    # 逻辑键 = (province_code, year, school_id, group_code, 批次, 首选科目)，
    # 与 rule_admin._import_identity 的 group 分支一致。
    # 口径（红线：宁可缺不可猜）：
    #   * 内容一致（first_subject / secondary_subjects / logic 全同）→ 折叠保留首条；
    #   * 内容冲突 → 全部排除并登记 conflicts 文件（人工复核后走管理端录入），
    #     引擎对无规则组返回 3001，绝不静默放行。
    def _content(r: dict) -> tuple:
        return (
            (r.get("first_subject") or ""),
            tuple(sorted(r.get("secondary_subjects") or [])),
            r.get("logic") or "all",
        )

    by_identity: dict[tuple, list[dict]] = {}
    for r in groups_ok:
        by_identity.setdefault(
            (
                r.get("province_code") or "", r.get("year"), r.get("school_id"),
                r.get("group_code"), _batch_code(r.get("batch")), _first_key(r.get("first_subject")),
            ),
            [],
        ).append(r)

    deduped: list[dict] = []
    folded_keys = folded_rows = 0
    conflicts: list[dict] = []
    for key, val in by_identity.items():
        if len(val) > 1 and len({_content(x) for x in val}) > 1:
            conflicts.append({
                "key": {"province_code": key[0], "year": key[1],
                        "school_id": key[2], "group_code": key[3],
                        "batch_code": key[4], "first_subject": key[5]},
                "rows": val,
            })
            continue
        deduped.append(val[0])
        if len(val) > 1:
            folded_keys += 1
            folded_rows += len(val) - 1
    conflict_rows = sum(len(c["rows"]) for c in conflicts)
    # 同一 (校, 组号) 在不同批次/科类下的多口径行（合法：招生计划按科类独立编组号）
    span: dict[tuple, set] = {}
    for r in deduped:
        span.setdefault((r.get("province_code"), r.get("school_id"), r.get("group_code")), set()).add(
            (_batch_code(r.get("batch")), _first_key(r.get("first_subject")))
        )
    variant_keys = sum(1 for v in span.values() if len(v) > 1)
    print(f"[cut] 组级折叠：{folded_keys} 键（去重 {folded_rows} 行）")
    print(f"[cut] 内容冲突排除：{len(conflicts)} 键 / {conflict_rows} 行（登记 conflicts 待复核）")
    print(f"[cut] 同组多口径保留（跨批次/科类）：{variant_keys} 键")
    print(f"[cut] 去重后可导入：{len(deduped)} 行")

    if args.dry_run:
        return 0

    STAGED_DIR.mkdir(parents=True, exist_ok=True)

    # 清理上一次生成的包，避免编号残留（如 15 包 → 13 包时的 part-…-014/015）
    stale = sorted(STAGED_DIR.glob("part-*.json"))
    for p in stale:
        p.unlink()
    if stale:
        print(f"[cln] 清理旧包 {len(stale)} 个")

    # ---- 按 (province, year) 分组切包 ----
    by_key: dict[tuple, list[dict]] = {}
    for r in deduped:
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
                "exam_type": "普通",
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

    # ---- 组级内容冲突（未导入，待人工复核）----
    if conflicts:
        cf = STAGED_DIR / "subject-requirement-group-conflicts.json"
        cf.write_text(json.dumps({
            "meta": {
                "title": "选科要求组级冲突行（同键多口径，未导入待复核）",
                "reason": "同一 (province_code, year, school_id, group_code, batch_code, first_subject) "
                          "逻辑键下存在内容不一致的多行，无法在不猜测的前提下合并；"
                          "导入通道亦按逻辑键拒收重复。",
                "next_step": "人工逐条复核后经管理端（契约 §8.8）录入或修正上游数据；"
                             "引擎对无规则组返回 3001（绝不静默放行）。",
                "counts": {"conflict_keys": len(conflicts), "conflict_rows": conflict_rows},
            },
            "conflicts": conflicts,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[out] {cf.name}  {len(conflicts)} 键 / {conflict_rows} 行")

    (STAGED_DIR / "manifest.json").write_text(json.dumps({
        "dataset": DATASET,
        "source_rows": len(rows),
        "importable": len(deduped),
        "identity": "province_code + year + school_id + group_code + batch_code + first_subject"
                    "（与 rule_admin._import_identity 一致）",
        "dedup": {
            "folded_keys": folded_keys,
            "folded_rows_removed": folded_rows,
            "conflict_keys": len(conflicts),
            "conflict_rows_excluded": conflict_rows,
            "variant_keys_kept": variant_keys,
        },
        "pending": {"major_level": len(pending), "unmatched_group": len(pending_no_school)},
        "api": "POST /api/admin/rule-datasets/import（契约 8.8，单次 ≤500）",
        "parts": parts,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[out] manifest.json（共 {len(parts)} 包 / 可导入 {len(deduped)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

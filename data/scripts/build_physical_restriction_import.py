# -*- coding: utf-8 -*-
"""
体检限制映射表 → 管理端规则导入包转换脚本（T5）
================================================
把 `data/dictionaries/physical-restriction.json` 转成契约 8.8
`POST /api/admin/rule-datasets/import`（dataset=physical_restriction，单次 ≤500、
整批事务）可直接投喂的导入包。**不手改产出数据文件**。

背景（同 T4）：`backend/app/services/rule_admin.py` 无 `RULE_DATASETS` 注册表；
实际通道 = `_IMPORT_BUILDERS[DATASET_PHYSICAL_RESTRICTION]`（`constants.py` 已注册）
+ 导入接口。无需改后端。
离线可复跑（红线）：仓库内 `data/majors/majors.json` 为必需基线，仓库外
`merged/major.json` 可选并入（口径同 `build_physical_restriction.py`）。

行展开规则（对齐 `PhysicalRestriction` 表；模型注释明确『空省码=全国』）：
  1. skip：scope=universal（体检结论类，档案无法覆盖，仅供展示）；
     PR-ARMY-05（占位条目，原文未核到，宁缺不猜）；superseded 区（乙肝条目）。
  2. major_menlei（工学/农学/医学/法学）→ 按专业库展开为具体专业类再入库。
  3. major_categories（类级）→ 一行/类：major_category=类名, major_code=""。
  4. major_names（点名专业）→ 一行/专业：major_category=其类, major_code=专业代码。
     **约定：major_code 非空 ⇒ 专业级条目（仅限该专业），否则为类级条目。**
     该约定供 T6 按 (major_category, major_code) 精确过滤（表已有对应联合索引）。
  5. condition：军校/公安条目加后缀『（军队院校）/（公安院校）』——防止普通批次
     志愿误用军检/警检标准判档（军警体检系单独组织）。普适条目保持原样。
  6. level：blocker→reject，warning→not_suitable（契约枚举）。
  7. source 三要素：按条目所属依据分别填 4 个已登记来源之一。
  8. 普适判档开关：engine_ready=false 的条目**照常导入**（数据是真实标准，
     管理端应可见可维护）；是否参与引擎判档由 T6 依据 dict 的 engine_ready
     与 meta.engine_integration 决定。manifest 中单列『待引擎扩展』清单。
  9. 去重：同一 (year, condition, threshold, major_category, major_code) 逻辑键
     仅保留 1 行 —— 门类展开面与类级清单可能双计同一专业类（如医学门类展开
     已含「药学类」，规则又显式点名）。完全一致条目折叠；若出现内容差异则
     保留首条并在 manifest 登记（宁缺不猜，人工复核）。

产出：data/staged/physical-restriction-import/（中间层，不入库）
  part-001.json / part-002.json …        → 导入请求体
  manifest.json                          → 汇总（含待引擎扩展清单）

用法：
  python build_physical_restriction_import.py            # 生成
  python build_physical_restriction_import.py --dry-run  # 只看统计
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # data/
DICT_PATH = BASE_DIR / "dictionaries" / "physical-restriction.json"
# 离线可复跑（红线，与 build_physical_restriction.py 同口径）：
#   仓库内 data/majors/majors.json（845 专业 / 93 专业类 / 12 门类）为必需基线；
#   仓库外整合产物 merged/major.json 若在本机则并入（仅扩大覆盖，缺失只提示）。
CATALOG_MAJOR = BASE_DIR / "majors" / "majors.json"
MERGE_MAJOR = Path(r"C:\Users\Administrator\Desktop\智选志愿_数据整合\merged\major.json")
STAGED_DIR = BASE_DIR / "staged" / "physical-restriction-import"
CHUNK = 500

DATASET = "physical_restriction"
YEAR = 2026                       # 规则适用高考年份（与 province_exam_rule 一致）

SOURCE_META = {
    "SRC-MOE-PHYSICAL-GUIDE": {
        "source_name": "教育部、卫生部、中国残联《普通高等学校招生体检工作指导意见》"
                       "（教学〔2003〕3号）",
        "source_url": "https://gaokao.chsi.com.cn/zxdy/view--qid-436737,method-listBulletin,"
                      "showCurrent-ggq1,year-2005,start-0.dhtml",
        "source_type": "official",
    },
    "SRC-MOE-HEPB-2010": {
        "source_name": "教育部办公厅、卫生部办公厅《关于普通高等学校招生学生入学身体检查"
                       "取消乙肝项目检测有关问题的通知》（教学厅〔2010〕2号）",
        "source_url": "https://www.moe.gov.cn/srcsite/A15/moe_776/s3258/201002/t20100225_87433.html",
        "source_type": "official",
    },
    "SRC-ARMY-MEDICAL-STD": {
        "source_name": "《军队选拔军官和文职人员体检标准》（军队院校招生执行，"
                       "经教育部阳光高考平台转载摘录）",
        "source_url": "https://gaokao.chsi.com.cn/gkxx/zc/ss/202506/20250619/2293390263.html",
        "source_type": "official",
    },
    "SRC-MPS-POLICE-MEDICAL": {
        "source_name": "《公安院校公安专业招生体检标准》（公安部 2025 年执行版，"
                       "经教育部阳光高考平台转载全文）",
        "source_url": "https://gaokao.chsi.com.cn/gkxx/zc/ss/202506/20250624/2293390562.html",
        "source_type": "official",
    },
}

SKIP_RULE_IDS = {"PR-ARMY-05"}            # 占位条目（未核到原文）

SEV_DETAIL = {
    "blocker": "可不予录取（报得上可能被退档）",
    "warning": "不宜就读（知情提示，学校不得据此拒录）",
}
SCOPE_SUFFIX = {"military": "（军队院校）", "police": "（公安院校）"}
SCOPE_PREFIX = {"military": "军检：", "police": "警检："}


def load_menlei_map() -> dict[str, list[str]]:
    """门类 → 专业类展开面。

    **离线可复跑（红线）**：仓库内 ``data/majors/majors.json`` 为必需基线
    （缺失即报错）；仓库外 ``merged/major.json`` 存在则并入（口径同
    ``build_physical_restriction.py::load_major_index``，已核验两者对
    93 类 / 12 门类展开面逐项一致）。
    """
    catalog = json.loads(CATALOG_MAJOR.read_text(encoding="utf-8"))
    if not catalog.get("majors"):
        raise SystemExit(f"[err] 专业库为空：{CATALOG_MAJOR}（离线可复跑依赖此文件）")

    m: dict[str, set] = {}

    def _feed(men: str, cls: str) -> None:
        if men and cls:
            m.setdefault(men, set()).add(cls)

    for r in catalog.get("majors", []):                       # 基线：仓库内
        _feed((r.get("menlei") or "").strip(), (r.get("class_name") or "").strip())

    if MERGE_MAJOR.exists():                                  # 可选：仓库外整合产物
        merged = json.loads(MERGE_MAJOR.read_text(encoding="utf-8"))
        recs = merged.get("records") or merged.get("rows") or []
        for r in recs:
            _feed((r.get("category") or "").strip(), (r.get("first_class") or "").strip())
        print(f"[lib ] 并入仓库外整合产物 {MERGE_MAJOR}（{len(recs)} 专业）")
    else:
        print(f"[lib ] 仓库外整合产物不在本机（{MERGE_MAJOR}）——"
              f"按仓库内基线 {CATALOG_MAJOR.name} 运行，产出不受影响")

    if not m:
        raise SystemExit(f"[err] 门类展开面为空：{CATALOG_MAJOR}")
    print(f"[lib ] 门类 {len(m)} / 专业类 {len({c for v in m.values() for c in v})}")
    return {k: sorted(v) for k, v in m.items()}


def build_items(doc: dict, menlei_map: dict[str, list[str]]):
    items, skipped, need_engine = [], [], []
    counter = Counter()

    for rule in doc["rules"]:
        rid = rule["rule_id"]
        if rule["scope"] == "universal" or rid in SKIP_RULE_IDS:
            skipped.append({"rule_id": rid, "reason":
                            "universal（体检结论类，档案不可覆盖）" if rule["scope"] == "universal"
                            else "占位条目（原文未核到）"})
            continue

        condition = rule["condition"] + SCOPE_SUFFIX.get(rule["scope"], "")
        level = "reject" if rule["severity"] == "blocker" else "not_suitable"
        src = SOURCE_META[rule["source_id"]]
        prefix = SCOPE_PREFIX.get(rule["scope"], "")
        detail_base = f"{prefix}{SEV_DETAIL[rule['severity']]}；依据：{rule['basis']}。" \
                      f"{rule['remark']}"
        if not rule["engine_ready"]:
            need_engine.append({"rule_id": rid,
                                "reason": rule["engine_note"] or "需引擎/档案扩展后判档"})

        def mk(category: str, code: str, extra: str = "") -> dict:
            # 注意：不携带 province_code/province —— 由 payload 省级字段与
            # province_name_of 回填（接口要求 province_code 非空）。
            return {
                "year": YEAR,
                "condition": condition,
                "threshold": rule["threshold"],
                "major_category": category,
                "major_code": code,
                "level": level,
                "detail": detail_base + extra,
                "source_name": src["source_name"],
                "source_url": src["source_url"],
                "source_type": src["source_type"],
                "source_year": YEAR,
            }

        # 2. 门类展开
        for men in rule["major_menlei"]:
            for cls in menlei_map.get(men, []):
                items.append(mk(cls, ""))
                counter["menlei_expanded"] += 1
        # 3. 类级
        for cat in rule["major_categories"]:
            items.append(mk(cat, ""))
            counter["class"] += 1
        # 4. 点名专业（专业级条目：major_code 非空）
        for t in rule["major_trace"]:
            items.append(mk(t["class"], t["code"],
                            f"本条目仅限「{t['catalog_name']}」（专业级，非整类）。"))
            counter["major"] += 1
        # 5. 军校/公安：机构级条目（major_category 空 = 适用于该类院校全部专业；
        #    T6 依靠 condition 后缀区分，禁用于普通批次判档）
        if rule["mapping_level"] == "institution":
            items.append(mk("", "", "本条目适用于该类院校全部招生专业（体检单独组织）。"))
            counter["institution"] += 1

    return items, skipped, need_engine, counter


def dedup_items(items: list[dict]) -> tuple[list[dict], int, list[dict]]:
    """同一逻辑键只保留 1 行（与 rule_admin._import_identity 体检分支一致）。

    重复来源：门类展开面与类级清单可能对同一专业类双计（如医学门类展开
    已含「药学类」，规则又显式点名）→ 产出完全相同的两行。
    口径：完全一致 → 折叠；内容差异 → 保留首条并登记冲突（宁缺不猜）。
    """
    seen: dict[tuple, dict] = {}
    out: list[dict] = []
    identical_removed = 0
    conflicts: list[dict] = []
    for it in items:
        key = (it["year"], it["condition"], it["threshold"], it["major_category"], it["major_code"])
        prev = seen.get(key)
        if prev is None:
            seen[key] = it
            out.append(it)
        elif prev == it:
            identical_removed += 1
        else:
            conflicts.append({"key": list(key), "note": "内容差异，保留首条待人工复核"})
    return out, identical_removed, conflicts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    doc = json.loads(DICT_PATH.read_text(encoding="utf-8"))
    menlei_map = load_menlei_map()
    items, skipped, need_engine, counter = build_items(doc, menlei_map)
    items, dup_removed, dup_conflicts = dedup_items(items)

    print(f"[in ] {DICT_PATH}（规则 {len(doc['rules'])} 条 + superseded {len(doc['superseded'])} 条）")
    print(f"[cut] 跳过（不导入）：{len(skipped)} 条 {[s['rule_id'] for s in skipped]}")
    print(f"[cut] 展开条目：类级 {counter['class']} + 门类展开 {counter['menlei_expanded']}"
          f" + 专业级 {counter['major']} + 机构级 {counter['institution']} = 共 {len(items) + dup_removed} 条")
    print(f"[cut] 去重：折叠完全一致 {dup_removed} 条；内容冲突 {len(dup_conflicts)} 条"
          f"（最终 {len(items)} 条）")
    print(f"[cut] 待引擎扩展清单 {len(need_engine)} 条（照常导入，判档由 T6 过滤）：")
    for x in need_engine:
        print(f"       {x['rule_id']}  {x['reason'][:60]}")

    if args.dry_run:
        return 0

    STAGED_DIR.mkdir(parents=True, exist_ok=True)
    # 清理上一次生成的包，避免编号残留
    stale = sorted(STAGED_DIR.glob("part-*.json"))
    for p in stale:
        p.unlink()
    if stale:
        print(f"[cln] 清理旧包 {len(stale)} 个")
    # ⚠️ 接口硬约束：RuleDatasetImportRequest.province_code 必填（min_length=1），
    #    不允许空串 → 全国性规则按省逐份导出（沿用 constraint_seed 的逐省落行先例：
    #    河南 41 / 江西 36 各一份；引擎按省取数不受影响，管理端各自维护）。
    PROVINCES = [("41", "河南"), ("36", "江西")]
    parts = []
    for code, name in PROVINCES:
        for i in range(0, len(items), CHUNK):
            chunk = items[i:i + CHUNK]
            payload = {
                "dataset": DATASET,
                "province_code": code, "province": name, "year": YEAR,
                "batch_code": "", "exam_type": "普通",
                "items": chunk,
            }
            p = STAGED_DIR / f"part-{code}-{i // CHUNK + 1:03d}.json"
            p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            parts.append({"file": p.name, "province": name, "items": len(chunk)})
            print(f"[out] {p.name}  {len(chunk)} 条")

    (STAGED_DIR / "manifest.json").write_text(json.dumps({
        "dataset": DATASET,
        "api": "POST /api/admin/rule-datasets/import（契约 8.8，单次 ≤500）",
        "rule_count": len(doc["rules"]),
        "item_count": len(items),
        "by_kind": dict(counter),
        "dedup": {"identical_removed": dup_removed, "conflicts": dup_conflicts},
        "skipped": skipped,
        "need_engine_extension": need_engine,
        "conventions": {
            "省码": "接口要求 province_code 非空 → 全国性规则按省逐份导出（河南 41 / 江西 36，"
                    "沿用 constraint_seed 逐省落行先例）；引擎按省取数不受影响",
            "major_code": "非空 ⇒ 专业级条目（仅限该专业；表有 (major_category, major_code) 联合索引）；"
                          "空 ⇒ 类级条目",
            "condition 后缀": "军校/公安条目加『（军队院校）/（公安院校）』后缀，"
                              "禁用于普通批次判档",
            "level": "blocker→reject；warning→not_suitable",
        },
        "parts": parts,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[out] manifest.json（{len(parts)} 包 / {len(items)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

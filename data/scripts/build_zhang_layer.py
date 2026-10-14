#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""张分支数据接入 · 转换层（R1–R5）：张产物 → 我方 schema 的 JSONL。

**只转换、不写库**。写库由 `load_zhang_to_pg.py` 负责（追加语义 + 业务键幂等）。

实现的五条通用规则（见 `data/张分支数据接入规范_徐.md` §4）：

  R1  业务键 → 内部 id     张 `code`/`name` → 我方 `school.id`/`major.id`
                           （只用**精确匹配**；⛔ 禁用编辑距离）
  R2  枚举收敛到契约 v1.3    `source_type` 未映射 ⇒ **留 NULL，不猜**
  R3  类型收敛              与张的数值语义对齐，不引入张的 id
  R4  `pathway_name` → `pathway.id`   未命中**显式进台账**，不猜
  R5  三要素 → `source` 表   先登记去重，再给事实表挂 `source_id`

**本轮接入范围（免裁子集）**：`source` · `pathway_region` · `pathway_eligibility`
· `enrollment_rule` · `subject_requirement`。其余产物各有阻塞项，一律进台账、不转。

用法：
    python build_zhang_layer.py [--zhang DIR] [--out DIR] [--dsn DSN]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover
    print("需要 psycopg：pip install 'psycopg[binary]'", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DSN = os.getenv(
    "ZHIXUAN_DATABASE_URL",
    "postgresql://zhixuan:change-me@127.0.0.1:5432/zhixuan",
).replace("postgresql+psycopg://", "postgresql://")

IN_SCOPE = ["source", "pathway_region", "pathway_eligibility",
            "enrollment_rule", "subject_requirement"]

# 张产物（按表）——只列本轮要接的
SRC_FILES = {
    "pathway_region": ["jiangxi/output/pathway_region.json"],
    "pathway_eligibility": ["output/pathway_eligibility.json",
                            "jiangxi/output/pathway_eligibility.json"],
    "enrollment_rule": ["output/enrollment_rule.json"],
    "subject_requirement": ["jiangxi/output/subject_requirement.json"],
}

FULLWIDTH_PARENS = str.maketrans({"（": "", "）": "", "(": "", ")": ""})


def rows_of(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return doc
    return next((v for v in doc.values() if isinstance(v, list)), [])


def norm(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


class Ledger:
    """台账：把「没接进来的」按原因聚合计 + 留样本，不逐行刷屏。"""

    def __init__(self) -> None:
        self.buckets: dict[str, dict] = defaultdict(lambda: {"n": 0, "samples": []})

    def add(self, reason: str, sample: str, n: int = 1) -> None:
        b = self.buckets[reason]
        b["n"] += n
        if len(b["samples"]) < 8:
            b["samples"].append(sample)

    def dump(self) -> dict:
        return {k: {"n": v["n"], "samples": v["samples"]}
                for k, v in sorted(self.buckets.items(), key=lambda x: -x[1]["n"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zhang", default=r"C:/Users/lenovo/.pg16/zhang_data")
    ap.add_argument("--out", default=str(ROOT / "data" / "staged_golden_zhang"))
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    args = ap.parse_args()

    zbase = Path(args.zhang) / "data"
    if not zbase.is_dir():
        print(f"✗ 找不到 {zbase}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    raw: dict[str, list[dict]] = {}
    for t, files in SRC_FILES.items():
        acc: list[dict] = []
        for f in files:
            acc.extend(rows_of(zbase / f))
        raw[t] = acc

    # ── 读我方现状（id 映射 + 已有业务键） ── #
    with psycopg.connect(args.dsn, connect_timeout=15) as conn:
        cur = conn.cursor()
        code2sids: dict[str, list[tuple[int, str]]] = defaultdict(list)
        cur.execute("select code, id, name from school "
                    "where code is not null and code <> '' order by id")
        for c, i, n in cur.fetchall():
            code2sids[norm(c)].append((int(i), norm(n)))
        name2sid: dict[str, int] = {}
        cur.execute("select name, id from school")
        for n, i in cur.fetchall():
            name2sid.setdefault(norm(n), i)
        pname2id: dict[str, str] = {}
        cur.execute("select name, id from pathway")
        for n, i in cur.fetchall():
            pname2id[norm(n)] = i
        prov2code: dict[str, str] = {}
        cur.execute("select distinct province, province_code from province_exam_rule "
                    "where province_code is not null and province_code <> ''")
        for p, c in cur.fetchall():
            prov2code[norm(p)] = norm(c)
        src_seen: dict[tuple, int] = {}
        cur.execute("select id, source_name, source_url, year from source")
        for i, n, u, y in cur.fetchall():
            src_seen[(norm(n), norm(u), int(y))] = i
        cur.execute("select coalesce(max(id),0) from source")
        next_src_id = int(cur.fetchone()[0]) + 1

        ours_pr: set[tuple] = set()
        cur.execute("select pathway_id, province, county_name, year from pathway_region")
        for a, b, c, d in cur.fetchall():
            ours_pr.add((norm(a), norm(b), norm(c), int(d)))
        ours_pe: set[tuple] = set()
        cur.execute("select pathway_id, province, rule_type, year from pathway_eligibility")
        for a, b, c, d in cur.fetchall():
            ours_pe.add((norm(a), norm(b), norm(c), int(d)))
        ours_er: set[tuple] = set()
        # ⚠ 我方 school 表 1,366 个唯一 code 对应 1,453 行（校区/合作办学变体共享 code）
        #   ⇒ enrollment_rule 的增量判定必须用 **(code, year)**，不能用 (school_id, year)，
        #     否则同一 code 的不同变体会被误判为"我方没有"而重复灌。
        cur.execute("select s.code, er.year from enrollment_rule er "
                    "join school s on s.id = er.school_id")
        for a, b in cur.fetchall():
            ours_er.add((norm(a), int(b)))

    codes_doc = json.loads(
        (ROOT / "data" / "dictionaries" / "subject-require-codes.json").read_text(encoding="utf-8"))
    CODE2MEAN = {c["code"]: c for c in codes_doc["codes"]}

    ledger = Ledger()

    # ── R5：三要素登记（去重，沿用我方 (name,url,year) 唯一键） ── #
    src_rows: list[dict] = []
    for t, recs in raw.items():
        for r in recs:
            key = (norm(r.get("source_name")), norm(r.get("source_url")), int(r.get("year") or 0))
            if not (key[0] and key[1] and key[2]):
                ledger.add("source.三要素不全(拒入)", f"{t}: {key}")
                continue
            if key in src_seen:
                continue
            sid = next_src_id
            next_src_id += 1
            src_seen[key] = sid
            src_rows.append({
                "id": sid, "source_name": key[0], "source_url": key[1], "year": key[2],
                # ⭐ N26 待裁：'公开网络' 未映射 ⇒ 留 None，不猜
                "source_type": None,
                "fetched_at": None,
            })

    def sid_of(r: dict) -> int | None:
        return src_seen.get((norm(r.get("source_name")), norm(r.get("source_url")),
                             int(r.get("year") or 0)))

    # ── R4：途径名 → pathway.id ── #
    _r4_missed: set[tuple[str, str]] = set()      # 防同名未命中被反复记账

    def resolve_pathway(name: str, table: str) -> str | None:
        pid = pname2id.get(norm(name))
        if pid:
            return pid
        key = (table, norm(name))
        if key not in _r4_missed:
            _r4_missed.add(key)
            n = sum(1 for x in raw[table] if norm(x.get("pathway_name")) == norm(name))
            ledger.add(f"{table}.途径名未命中我方 26 类字典(R4)", norm(name), n=max(n, 1))
        return None

    # ── pathway_region ── #
    pr_rows: list[dict] = []
    pr_seen: set[tuple] = set()
    for r in raw["pathway_region"]:
        pid = resolve_pathway(r.get("pathway_name"), "pathway_region")
        if not pid:
            continue
        k = (pid, norm(r.get("province")), norm(r.get("county_name")), int(r.get("year")))
        if k in ours_pr:
            continue                                   # 与我方逐条重复 ⇒ 不算增量
        if k in pr_seen:
            ledger.add("pathway_region.张方自身重复键", str(k))
            continue
        pr_seen.add(k)
        pr_rows.append({
            "pathway_id": pid, "province": norm(r.get("province")),
            "county_name": norm(r.get("county_name")),
            "county_code": norm(r.get("county_code")) or None,
            "year": int(r.get("year")), "source_id": sid_of(r),
        })

    # ── pathway_eligibility ── #
    pe_rows: list[dict] = []
    pe_seen: set[tuple] = set()
    for r in raw["pathway_eligibility"]:
        pid = resolve_pathway(r.get("pathway_name"), "pathway_eligibility")
        if not pid:
            continue
        k = (pid, norm(r.get("province")), norm(r.get("rule_type")), int(r.get("year")))
        if k in ours_pe:
            ledger.add("pathway_eligibility.我方已有同键(非增量)", str(k))
            continue
        if k in pe_seen:
            ledger.add("pathway_eligibility.张方自身重复键", str(k))
            continue
        pe_seen.add(k)
        pe_rows.append({
            "pathway_id": pid, "province": norm(r.get("province")),
            "rule_type": norm(r.get("rule_type")), "rule_desc": norm(r.get("rule_desc")) or "",
            "params": r.get("params") or {}, "year": int(r.get("year")),
            "source_id": sid_of(r),
        })

    # ── R1：院校码 → school.id（⭐ 我方存在「同 code 多行」⇒ 必须消歧） ── #
    def resolve_school_by_code(code: str, sname: str) -> int | None:
        cands = code2sids.get(norm(code), [])
        if not cands:
            return None
        # ① 名称精确命中（最可靠）
        for i, n in cands:
            if n == norm(sname):
                return i
        # ② 该 code 在我方唯一
        if len(cands) == 1:
            return cands[0][0]
        # ③ 多候选：取"无括号后缀"的主实体（如 郑州轻工业大学 vs 郑州轻工业大学(中外合作办学)）
        plain = [i for i, n in cands if "(" not in n and "（" not in n]
        if len(plain) == 1:
            return plain[0]
        ledger.add("enrollment_rule.同 code 多候选且无法消歧(R1)",
                   f"{norm(code)} {norm(sname)} → {[n for _, n in cands]}")
        return None

    # ── enrollment_rule（只补我方缺的 (code, year)） ── #
    er_rows: list[dict] = []
    for r in raw["enrollment_rule"]:
        code = norm(r.get("school_code"))
        if (code, int(r.get("year"))) in ours_er:
            continue                                   # 我方已有同 code+year ⇒ 非增量
        sid = resolve_school_by_code(code, r.get("school_name"))
        if sid is None:
            ledger.add("enrollment_rule.院校码未命中我方 school.code(R1)", code)
            continue
        er_rows.append({
            "school_id": sid, "year": int(r.get("year")),
            "content": norm(r.get("content")),
            "subject_req": norm(r.get("subject_req")),
            "health_req": norm(r.get("health_req")),
            "foreign_lang_req": norm(r.get("foreign_lang_req")),
            "source_id": sid_of(r),
        })

    # ── subject_requirement（我方空表 ⇒ 全量为增量） ── #
    sr_rows: list[dict] = []
    logic_used: Counter = Counter()
    first_used: Counter = Counter()
    prov = "江西"
    for r in raw["subject_requirement"]:
        text = norm(r.get("subject_req"))
        mm = re.search(r"首选(物理|历史|不限)", text)
        if not mm:
            ledger.add("subject_requirement.首选科目无法从 subject_req 判定", text or "(空)")
            continue
        first = mm.group(1)
        # 交叉核对张自带的 first_require（2696 行为空，属其抽取缺陷 ⇒ 以文本为准）
        fr = norm(r.get("first_require"))
        if fr and fr != first:
            ledger.add("subject_requirement.first_require 与 subject_req 文本冲突",
                       f"{fr} vs {first}")
            continue
        if not fr:
            ledger.add("subject_requirement.first_require 空(已由 subject_req 文本还原)",
                       f"{first}", n=1)

        code = norm(r.get("second_require"))
        info = CODE2MEAN.get(code)
        if info is None:
            ledger.add("subject_requirement.科目码不在 E3 字典中", code)
            continue
        sec = [] if info.get("is_unlimited") else list(info.get("members") or [])
        logic = "all"          # 源文本「(2科必选)」⇒ 必选；单科 all/any 语义等价
        logic_used[logic] += 1
        first_used[first] += 1

        sid = name2sid.get(norm(r.get("school_name")))
        if sid is None:
            # ⭐ 与我方金层同一纪律：**空 FK 的行不入库**（无 school_id 的要求行无法被联接使用，
            #   且表内无 school_name 列可留痕）⇒ 剔出台账，等校名归一后补采。
            ledger.add("subject_requirement.校名未精确命中我方 school.name ⇒ 剔出台账(R1)",
                       norm(r.get("school_name")))
            continue
        s = sid_of(r)
        if s is None:
            ledger.add("subject_requirement.source_id 解析失败", text)
            continue
        sr_rows.append({
            "province": prov,
            "province_code": prov2code.get(prov, ""),   # G6：规则表用 2 位省码
            "year": int(r.get("year")),
            "batch": "",                                # 张无 batch 维度 ⇒ 取列默认值
            "school_id": sid,                           # 允许 NULL（列可空）
            "group_code": norm(r.get("group_name")).translate(FULLWIDTH_PARENS) or None,
            "major_id": None,                           # 张无专业维度
            "first_subject": first,
            "secondary_subjects": sec,
            "logic": logic,
            "source_id": s,
        })

    tables = {"source": src_rows, "pathway_region": pr_rows,
              "pathway_eligibility": pe_rows, "enrollment_rule": er_rows,
              "subject_requirement": sr_rows}

    for t in IN_SCOPE:
        fp = out / f"{t}.jsonl"
        with fp.open("w", encoding="utf-8") as fh:
            for r in tables[t]:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  {t:22s} {len(tables[t]):>7} 行 → {fp.name}")

    plan = {
        "_scope": IN_SCOPE,
        "rows": {t: len(tables[t]) for t in IN_SCOPE},
        "source_type": "全部为 NULL —— N26 未裁（'公开网络' 未映射）",
        "subject_requirement": {
            "logic 取值": dict(logic_used),
            "first_subject 取值": dict(first_used),
            "school_id 已解析": sum(1 for x in sr_rows if x["school_id"] is not None),
            "school_id 未解析(NULL)": sum(1 for x in sr_rows if x["school_id"] is None),
        },
        "province_code 来源": "province_exam_rule（G6 口径：江西=36）",
        "_findings": {
            "school_code_非唯一": {
                "我方 school 行数": len(name2sid),
                "我方唯一 code 数": len(code2sids),
                "含义": "87 个「校区/合作办学变体」共享同一国标 code",
                "后果": "R1 按 code 解析必须配 name 消歧；enrollment_rule 增量判定用 (code,year)",
            }
        },
    }
    (out / "_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    ld = ledger.dump()
    (out / "_ledger.json").write_text(json.dumps(ld, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    print("\n=== 计划 ===")
    print(json.dumps(plan["rows"], ensure_ascii=False))
    print(f"  subject_requirement: school_id 已解析 "
          f"{plan['subject_requirement']['school_id 已解析']} / "
          f"NULL {plan['subject_requirement']['school_id 未解析(NULL)']}；"
          f"first_subject {plan['subject_requirement']['first_subject 取值']}")
    print("\n=== 台账（未接入，按原因聚合）===")
    for k, v in ld.items():
        print(f"  {v['n']:>6}  {k}")
        for s in v["samples"][:3]:
            print(f"           · {s}")
    print(f"\n输出目录：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

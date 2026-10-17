"""语料导入包生成与落库 CLI（契约 8.2 语料通道的批量形态；产品书 6.6.2 / M3-1）。

    cd backend
    # 1) 从库内结构化数据文本化为语料包
    python -m app.services.corpus_packs --build --out ../data/staged/knowledge-import
    # 2) 落库（chunks 缺省自动切块；幂等）
    python -m app.services.corpus_packs --import-dir ../data/staged/knowledge-import

``--build``（产品书 M3-1「结构化数据文本化」）从当前库生成四类语料包：
  - ``pack-pathways.json``       途径说明：pathway 主表（批次/人群/时间/简述）
                                  + pathway_eligibility 资格规则拼装；来源=行级 source。
  - ``pack-school-intros.json``  院校简介：``school.intro`` 非空院校；
                                  来源=合并集为院校行登记的来源闸门（不新造来源）。
  - ``pack-major-intros.json``   专业介绍：``major.intro`` 非空专业；
                                  来源=专业目录来源。
  - ``pack-scores-{省}.json``    录取分汇总：``school_major_score`` 按
                                  校×年×批×科（×途径）聚合，**只聚合、不推算**；
                                  科类/批次缺失的记录按原样归入「未注明」；
                                  来源=行级 source（Gaokao-Compass-11M）。

``--import-dir``：``pack-*.json`` 逐篇走 ``corpus_service.create_doc``（与
``POST /api/admin/docs`` 同一服务路径：4001 拒收、审计留痕、途径存在性校验），
CLI 不复刻任何校验逻辑：
  - ``chunks`` 缺省/为空且 content 非空 → ``rag.chunking.split_chunks`` 自动切块；
  - 幂等：同 ``(title, source_name, source_url, year)`` 已在库 → 记 skip；
  - 单篇失败不中断整批，如实登记失败原因。

退出码：0 = 全部成功或幂等跳过；1 = 存在失败；2 = 环境问题（缺管理员、缺目录、
来源未登记）。中文输出建议 ``PYTHONIOENCODING=utf-8``。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.core.response import BizError
from app.db.session import SessionLocal
from app.models.base_data import Major, School, SchoolMajorScore
from app.models.knowledge import AdminUser, KnowledgeDoc
from app.models.pathway import Pathway, PathwayEligibility
from app.models.source import Source
from app.rag.chunking import split_chunks
from app.schemas.admin import DocCreateRequest
from app.services import corpus as corpus_service

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = ROOT / "data" / "staged" / "knowledge-import"

# school / major 为基础字典表（无 source_id 列）。合并集为每一行戳了真实的
# 「来源闸门」id（merge_datasets.py：school→SRC-HENAN-ZSJH，major→SRC-MOE-ZHUANYE-2025），
# 本 CLI 按登记名取回这两条来源，不新造、不猜测。
SCHOOL_INTRO_SOURCE_NAME = "河南省阳光高考信息平台（招生计划查询系统）"
MAJOR_INTRO_SOURCE_NAME = "中华人民共和国教育部《普通高等学校本科专业目录（2025年）》"

SCORE_DATA_NOTE = (
    "数据说明：本页由 Gaokao-Compass-11M 数据集的分专业组原始录取记录汇总生成，"
    "仅做聚合、不推算；「最低分」为各专业组最低分中的最小值；"
    "科类或批次缺失的记录按原样归入「未注明」。"
)


def _source_triple(source: Source | None) -> dict[str, Any]:
    return {
        "source_name": (source.source_name if source else "") or "",
        "source_url": (source.source_url if source else "") or "",
        "year": int((source.year if source else 0) or 0),
    }


def _resolve_source_by_name(db, name: str) -> Source | None:
    exact = db.scalars(select(Source).where(Source.source_name == name)).all()
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise SystemExit(f"[corpus_packs] 来源名不唯一：{name}（{len(exact)} 行）")
    return None


# ---------------------------------------------------------------------------
# --build：结构化数据文本化（产品书 M3-1）
# ---------------------------------------------------------------------------

def _pack_pathways(db) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    elig_by_pathway: dict[str, list[PathwayEligibility]] = defaultdict(list)
    for row in db.scalars(select(PathwayEligibility).order_by(PathwayEligibility.id)).all():
        elig_by_pathway[row.pathway_id].append(row)

    for p in db.scalars(select(Pathway).order_by(Pathway.priority, Pathway.id)).all():
        source = db.get(Source, p.source_id)
        lines = [f"{p.name}（途径分类：{p.category or '未注明'}）", "", "【途径概览】"]
        if p.batch:
            lines.append(f"- 录取批次：{p.batch}")
        if p.target_group:
            lines.append(f"- 面向人群：{p.target_group}")
        if p.apply_time:
            lines.append(f"- 报名 / 填报时间：{p.apply_time}")
        if p.description:
            lines.append(f"- 途径简介：{p.description}")

        rules = elig_by_pathway.get(p.id) or []
        if rules:
            lines += ["", f"【报考资格条件（{rules[0].year}）】"]
            for rule in rules:
                scope = rule.province or "通用"
                lines.append(f"- {rule.rule_type}（{scope}）：{rule.rule_desc}")
        lines += [
            "",
            "（说明：以上为途径字典与资格规则的库内登记内容，供概览检索；"
            "具体报考以当年省级招生文件为准。）",
        ]
        docs.append({
            "title": f"升学途径说明：{p.name}",
            **_source_triple(source),
            "doc_type": "途径说明",
            "province": "",
            "pathway_id": p.id,
            "content": "\n".join(lines),
        })
    return {"pack": "pathways", "description": "26 类升学途径：字典 + 资格规则文本化", "docs": docs}


def _pack_school_intros(db, *, source: Source | None) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    rows = db.scalars(
        select(School)
        .where(School.intro.isnot(None), School.intro != "")
        .order_by(School.id)
    ).all()
    for s in rows:
        tags: list[str] = []
        if s.level:
            tags.append(s.level)
        if s.ownership:
            tags.append(s.ownership)
        if s.is_985:
            tags.append("985 工程")
        if s.is_211:
            tags.append("211 工程")
        if s.dual_class:
            tags.append(s.dual_class)
        lines = [f"{s.name}（{s.province}·{s.city}）"]
        if tags:
            lines += ["", f"【办学信息】{'｜'.join(tags)}"]
        if s.website:
            lines.append(f"【院校官网】{s.website}")
        lines += ["", f"【院校简介】{s.intro.strip()}"]
        docs.append({
            "title": f"院校简介：{s.name}",
            **_source_triple(source),
            "doc_type": "院校简介",
            "province": s.province or "",
            "pathway_id": None,
            "content": "\n".join(lines),
        })
    return {"pack": "school-intros", "description": "院校简介文本化（school.intro）", "docs": docs}


def _pack_major_intros(db, *, source: Source | None) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    rows = db.scalars(
        select(Major)
        .where(Major.intro.isnot(None), Major.intro != "")
        .order_by(Major.id)
    ).all()
    for m in rows:
        head = m.name
        if m.code:
            head += f"（专业代码 {m.code}）"
        lines = [head]
        meta: list[str] = []
        if m.category:
            meta.append(f"学科门类/专业类：{m.category}")
        if m.degree:
            meta.append(f"授予学位：{m.degree}")
        if m.duration:
            meta.append(f"学制：{m.duration}")
        if m.first_class:
            meta.append(f"建设点：{m.first_class}")
        if meta:
            lines += ["", "【专业信息】" + "；".join(meta)]
        lines += ["", f"【专业简介】{m.intro.strip()}"]
        docs.append({
            "title": f"专业介绍：{m.name}",
            **_source_triple(source),
            "doc_type": "专业介绍",
            "province": "",
            "pathway_id": None,
            "content": "\n".join(lines),
        })
    return {"pack": "major-intros", "description": "专业介绍文本化（major.intro）", "docs": docs}


def _pack_scores(db, province: str) -> dict[str, Any]:
    """录取分汇总：校×年×批×科（×途径）聚合，只聚合不推算。"""
    source_by_id: dict[int, Source] = {
        int(row.id): row
        for row in db.scalars(
            select(Source).where(
                Source.id.in_(
                    select(SchoolMajorScore.source_id)
                    .where(SchoolMajorScore.province == province)
                    .distinct()
                )
            )
        ).all()
    }

    aggregates = db.execute(
        select(
            SchoolMajorScore.school_id,
            SchoolMajorScore.year,
            SchoolMajorScore.batch,
            SchoolMajorScore.subject_type,
            SchoolMajorScore.pathway_id,
            func.min(SchoolMajorScore.min_score),
            func.min(SchoolMajorScore.min_rank),
            func.count(),
        )
        .where(SchoolMajorScore.province == province, SchoolMajorScore.school_id.isnot(None))
        .group_by(
            SchoolMajorScore.school_id,
            SchoolMajorScore.year,
            SchoolMajorScore.batch,
            SchoolMajorScore.subject_type,
            SchoolMajorScore.pathway_id,
        )
        .order_by(SchoolMajorScore.school_id, SchoolMajorScore.year.desc())
    ).all()

    by_school: dict[int, list[tuple]] = defaultdict(list)
    for row in aggregates:
        by_school[int(row[0])].append(row)

    docs: list[dict[str, Any]] = []
    for school_id, rows in sorted(by_school.items()):
        school = db.get(School, school_id)
        if school is None:
            continue
        year_min = min(int(row[1]) for row in rows)
        year_max = max(int(row[1]) for row in rows)
        head = f"{school.name}（{school.province}·{school.city}）"
        tags: list[str] = []
        if school.is_985:
            tags.append("985")
        if school.is_211:
            tags.append("211")
        if school.dual_class:
            tags.append("双一流")
        if tags:
            head += "｜" + "·".join(tags)
        title_years = f"{year_min}–{year_max}" if year_min != year_max else str(year_max)
        lines = [f"{head} 历年{province}录取分数汇总（{title_years}）", "", SCORE_DATA_NOTE, ""]

        # 按年份分组输出
        rows_by_year: dict[int, list[tuple]] = defaultdict(list)
        for row in rows:
            rows_by_year[int(row[1])].append(row)
        for year in sorted(rows_by_year, reverse=True):
            for row in sorted(rows_by_year[year], key=lambda r: (r[2] or "", r[3] or "")):
                _sid, _year, batch, subject, pathway_id, min_score, min_rank, count = row
                batch_label = batch or "未注明批次"
                subject_label = subject or "未注明科类"
                score_label = f"最低分 {int(min_score)}" if min_score is not None else "最低分缺失"
                if min_rank is not None:
                    score_label += f"，最低位次 {int(min_rank)}"
                suffix = f"（途径：{pathway_id}）" if pathway_id else ""
                lines.append(
                    f"{year}｜{batch_label}｜{subject_label}：{score_label}"
                    f"（汇总自 {int(count)} 条原始记录）{suffix}"
                )
            lines.append("")

        # 来源：聚合行涉及的来源（通常为 Gaokao-Compass-11M 一条；多条时取行数最多者）
        src_rows = db.execute(
            select(SchoolMajorScore.source_id, func.count())
            .where(
                SchoolMajorScore.province == province,
                SchoolMajorScore.school_id == school_id,
            )
            .group_by(SchoolMajorScore.source_id)
            .order_by(func.count().desc())
        ).all()
        main_source = source_by_id.get(int(src_rows[0][0])) if src_rows else None
        docs.append({
            "title": f"{school.name} 在{province} 历年录取分数汇总（{title_years}）",
            **_source_triple(main_source),
            "doc_type": "录取数据",
            "province": province,
            "pathway_id": None,
            "content": "\n".join(lines).rstrip() + "\n",
        })
    return {
        "pack": f"scores-{province}",
        "description": f"{province}录取分按校×年×批×科聚合文本化（school_major_score）",
        "docs": docs,
    }


def build_packs(db, *, provinces: list[str], out_dir: Path) -> dict[str, Any]:
    school_source = _resolve_source_by_name(db, SCHOOL_INTRO_SOURCE_NAME)
    major_source = _resolve_source_by_name(db, MAJOR_INTRO_SOURCE_NAME)
    missing = [
        name for name, src in (
            (SCHOOL_INTRO_SOURCE_NAME, school_source),
            (MAJOR_INTRO_SOURCE_NAME, major_source),
        ) if src is None
    ]
    if missing:
        raise SystemExit(
            "[corpus_packs] 来源未登记（合并集来源闸门缺失）："
            + "；".join(missing)
            + "。请先在 source 表登记后再生成。"
        )

    packs = [
        _pack_pathways(db),
        _pack_school_intros(db, source=school_source),
        _pack_major_intros(db, source=major_source),
    ]
    packs.extend(_pack_scores(db, p) for p in provinces)

    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"out": str(out_dir), "packs": []}
    for pack in packs:
        path = out_dir / f"pack-{pack['pack']}.json"
        path.write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
        total_chars = sum(len(d.get("content") or "") for d in pack["docs"])
        report["packs"].append({"file": path.name, "docs": len(pack["docs"]), "chars": total_chars})
        print(f"[corpus_packs] 生成 {path.name}：{len(pack['docs'])} 篇 / {total_chars} 字")
    return report


# ---------------------------------------------------------------------------
# --import-dir：批量落库（走 corpus_service.create_doc 同一通道）
# ---------------------------------------------------------------------------

def _doc_exists(db, doc: dict[str, Any]) -> bool:
    return db.scalar(
        select(KnowledgeDoc.id).where(
            KnowledgeDoc.title == str(doc.get("title") or ""),
            KnowledgeDoc.source_name == str(doc.get("source_name") or ""),
            KnowledgeDoc.source_url == str(doc.get("source_url") or ""),
            KnowledgeDoc.year == int(doc.get("year") or 0),
        ).limit(1)
    ) is not None


def _import_doc(db, doc: dict[str, Any], admin: AdminUser) -> dict[str, Any]:
    if _doc_exists(db, doc):
        return {"action": "skip", "title": doc.get("title")}
    chunks = [c for c in (doc.get("chunks") or []) if str(c).strip()]
    content = str(doc.get("content") or "")
    if not chunks and content.strip():
        chunks = split_chunks(content)
    try:
        payload = DocCreateRequest(
            title=str(doc.get("title") or "").strip(),
            source_name=str(doc.get("source_name") or ""),
            source_url=str(doc.get("source_url") or ""),
            year=int(doc.get("year") or 0),
            doc_type=str(doc.get("doc_type") or ""),
            province=str(doc.get("province") or ""),
            pathway_id=(str(doc.get("pathway_id")).strip() or None) if doc.get("pathway_id") else None,
            content=content,
            chunks=chunks,
        )
        result = corpus_service.create_doc(db, payload, admin, client_ip="cli:corpus_packs")
    except BizError as exc:
        return {"action": "fail", "title": doc.get("title"), "reason": str(exc.message)[:200]}
    return {
        "action": "import",
        "title": doc.get("title"),
        "doc_id": result.get("doc_id"),
        "chunks": result.get("chunk_count"),
    }


def import_dir(db, directory: Path, admin: AdminUser) -> dict[str, Any]:
    files = sorted(directory.glob("pack-*.json"))
    if not files:
        print(f"[corpus_packs] 目录无 pack-*.json：{directory}")
        raise SystemExit(2)
    report: dict[str, Any] = {"dir": str(directory), "packs": [], "imported": 0, "skipped": 0,
                              "failed": 0, "chunks": 0}
    for path in files:
        pack = json.loads(path.read_text(encoding="utf-8"))
        outcomes = []
        for doc in pack.get("docs") or []:
            outcome = _import_doc(db, doc, admin)
            outcomes.append(outcome)
            if outcome["action"] == "import":
                report["imported"] += 1
                report["chunks"] += int(outcome.get("chunks") or 0)
            elif outcome["action"] == "skip":
                report["skipped"] += 1
            else:
                report["failed"] += 1
        summary = {
            "file": path.name,
            "docs": len(pack.get("docs") or []),
            "imported": sum(1 for o in outcomes if o["action"] == "import"),
            "skipped": sum(1 for o in outcomes if o["action"] == "skip"),
            "failed": sum(1 for o in outcomes if o["action"] == "fail"),
        }
        failures = [o for o in outcomes if o["action"] == "fail"]
        if failures:
            summary["failures"] = [
                {"title": f.get("title"), "reason": f.get("reason")} for f in failures[:10]
            ]
        report["packs"].append(summary)
        print(
            f"[corpus_packs] {path.name}: docs={summary['docs']} "
            f"import={summary['imported']} skip={summary['skipped']} fail={summary['failed']}"
        )
        for f in failures[:5]:
            print(f"    FAIL {f.get('title')}: {f.get('reason')}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="语料包生成与批量落库（契约 8.2 通道）")
    parser.add_argument("--build", action="store_true", help="从库内结构化数据生成语料包")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="生成目录（--build）")
    parser.add_argument("--provinces", default="河南",
                        help="录取分汇总覆盖省份，逗号分隔（默认：河南）")
    parser.add_argument("--import-dir", type=Path, default=None, help="落库目录")
    parser.add_argument("--report", type=Path, default=None, help="报告 JSON 输出路径")
    args = parser.parse_args(argv)

    if not args.build and args.import_dir is None:
        parser.error("至少指定 --build 或 --import-dir 之一")

    provinces = [p.strip() for p in args.provinces.split(",") if p.strip()]
    with SessionLocal() as db:
        reports: dict[str, Any] = {}
        if args.build:
            reports["build"] = build_packs(db, provinces=provinces, out_dir=args.out)
        if args.import_dir is not None:
            admin = db.scalars(select(AdminUser).order_by(AdminUser.id)).first()
            if admin is None:
                print("[corpus_packs] 库内无管理端用户，导入通道需要审计主体；请先创建管理员。")
                return 2
            reports["import"] = import_dir(db, args.import_dir, admin)
            imp = reports["import"]
            print(
                f"[corpus_packs] 合计：import={imp['imported']} skip={imp['skipped']} "
                f"fail={imp['failed']} chunks={imp['chunks']}"
            )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(reports, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        failed = bool(reports.get("import", {}).get("failed"))
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""语料切块与批量导入 CLI 离线验收（不联网、不下载模型；产品书 M3-1 / 6.6.2）。

覆盖：
- rag.chunking.split_chunks：纯函数性质（空文本、短文本、长段切分、短段合并、
  保序不丢字、参数校验）；
- services.corpus_packs：--build 生成的语料包结构（来源三要素 / 元数据 / 正文）、
  --import-dir 落库（chunks 自动切块、幂等 skip、缺来源 4001 记失败不中断）。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from sqlalchemy import select

_work = Path(tempfile.mkdtemp(prefix="zhixuan_corpus_packs_"))
os.environ["ZHIXUAN_DATABASE_URL"] = f"sqlite:///{(_work / 'corpus.db').as_posix()}"
os.environ["ZHIXUAN_SECRET_KEY"] = "test-secret-key-corpus-packs-suite-at-least-32bytes"
os.environ["ZHIXUAN_ENV"] = "test"

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.models.base_data import Major, School, SchoolMajorScore  # noqa: E402
from app.models.knowledge import AdminUser, KnowledgeChunk, KnowledgeDoc  # noqa: E402
from app.models.pathway import Pathway, PathwayEligibility  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.rag.chunking import split_chunks  # noqa: E402
from app.schemas.admin import DocCreateRequest  # noqa: E402
from app.services import corpus as corpus_service  # noqa: E402
from app.services import corpus_packs  # noqa: E402

create_all()

SCHOOL_SOURCE_NAME = corpus_packs.SCHOOL_INTRO_SOURCE_NAME
MAJOR_SOURCE_NAME = corpus_packs.MAJOR_INTRO_SOURCE_NAME


def _seed_db() -> None:
    with SessionLocal() as db:
        db.add(AdminUser(username="admin", password_hash="x" * 60, role="admin"))

        src_official = Source(source_name="河南省教育考试院", source_url="https://www.haeea.cn/",
                              year=2025, source_type="official")
        src_school = Source(source_name=SCHOOL_SOURCE_NAME,
                            source_url="https://zsjh.haedu.cn/qwerasd/school", year=2026)
        src_major = Source(source_name=MAJOR_SOURCE_NAME,
                           source_url="https://www.moe.gov.cn/srcsite/A08/moe_1034/s4930/", year=2025)
        src_score = Source(source_name="Gaokao-Compass-11M 高考数据集（MIT，DOI 10.57967/hf/9882）",
                           source_url="https://hf-mirror.com/datasets/choucsan/Gaokao-Compass-11M",
                           year=2025)
        db.add_all([src_official, src_school, src_major, src_score])
        db.flush()

        db.add(Pathway(
            id="national-special", name="国家专项计划", category="专项计划", batch="本科批",
            target_group="实施区域农村户籍学生（38县）", apply_time="高考后填报志愿",
            description="面向集中连片特困及国家级扶贫开发重点县的农村学生",
            priority="P0", year=2025, source_id=src_official.id,
        ))
        db.add(PathwayEligibility(
            pathway_id="national-special", province="河南", rule_type="区域",
            rule_desc="考生户籍须在国家专项计划实施区域（河南省 38 县）内",
            year=2025, source_id=src_official.id,
        ))

        school = School(name="郑州大学", province="河南", city="郑州市", level="本科",
                        type="综合", ownership="公办", is_211=True,
                        dual_class="一流大学建设高校",
                        intro="郑州大学由河南省人民政府举办，法定住所地为河南省郑州市科学大道100号。")
        db.add(school)
        db.flush()
        major = Major(name="哲学", code="010101", category="哲学", degree="哲学学士",
                      intro="哲学是研究中西现代哲学、中西哲学史、伦理学、逻辑学等方面的基本理论和知识。")
        db.add(major)
        db.flush()
        db.add_all([
            SchoolMajorScore(school_id=school.id, province="河南", year=2025, batch="本科批",
                             subject_type="物理类", group_code="302", min_score=601,
                             min_rank=15852, source_id=src_score.id),
            SchoolMajorScore(school_id=school.id, province="河南", year=2024, batch="本科一批",
                             subject_type="理科", group_code="15", min_score=586,
                             min_rank=32000, source_id=src_score.id),
        ])
        db.commit()


def test_chunking_basic_properties() -> None:
    assert split_chunks("") == []
    assert split_chunks("   \n  \n ") == []
    short = "河南省2026年普通本科一批省控线为465分。"
    assert split_chunks(short) == [short]

    # 长段落：按句切且每块不超过 max_len
    long_para = "平行志愿按分数优先、遵循志愿顺序投档。" * 40  # ~680 字
    chunks = split_chunks(long_para, target=200, max_len=300, min_len=50)
    assert len(chunks) >= 2
    assert all(len(c) <= 300 for c in chunks)
    # 不丢字：去空白后拼接一致
    assert "".join(chunks).split() == long_para.split()

    # 短段合并：多个短段应尽量拼到 target 附近，而不是一片一段
    paragraphs = "\n\n".join(f"第{i}条规则内容。" for i in range(1, 13))  # 12 个 ~9 字短段
    merged = split_chunks(paragraphs, target=100, max_len=200, min_len=30)
    assert 1 <= len(merged) <= 3, f"短段未合并：{[len(m) for m in merged]}"

    # 参数非法应拒绝
    try:
        split_chunks("正文", target=300, max_len=200, min_len=120)
        raise AssertionError("参数非法未被拒绝")
    except ValueError:
        pass


def test_build_packs_structure() -> None:
    _seed_db()
    with SessionLocal() as db:
        out_dir = _work / "packs"
        report = corpus_packs.build_packs(db, provinces=["河南"], out_dir=out_dir)

    files = {p["file"] for p in report["packs"]}
    assert files == {
        "pack-pathways.json", "pack-school-intros.json",
        "pack-major-intros.json", "pack-scores-河南.json",
    }, files

    pathways = json.loads((out_dir / "pack-pathways.json").read_text(encoding="utf-8"))
    doc = pathways["docs"][0]
    assert doc["title"] == "升学途径说明：国家专项计划"
    assert doc["pathway_id"] == "national-special"
    assert doc["doc_type"] == "途径说明"
    assert doc["source_name"] == "河南省教育考试院"
    assert doc["source_url"].startswith("https://www.haeea.cn")
    assert doc["year"] == 2025
    assert "考生户籍须在国家专项计划实施区域" in doc["content"]
    assert "面向集中连片特困" in doc["content"]

    schools = json.loads((out_dir / "pack-school-intros.json").read_text(encoding="utf-8"))
    doc = schools["docs"][0]
    assert doc["title"] == "院校简介：郑州大学"
    assert doc["province"] == "河南"
    assert doc["source_name"] == SCHOOL_SOURCE_NAME
    assert "211 工程" in doc["content"] and "科学大道100号" in doc["content"]

    majors = json.loads((out_dir / "pack-major-intros.json").read_text(encoding="utf-8"))
    doc = majors["docs"][0]
    assert doc["title"] == "专业介绍：哲学"
    assert doc["source_name"] == MAJOR_SOURCE_NAME
    assert "逻辑学" in doc["content"]

    scores = json.loads((out_dir / "pack-scores-河南.json").read_text(encoding="utf-8"))
    doc = scores["docs"][0]
    assert doc["title"].startswith("郑州大学 在河南 历年录取分数汇总")
    assert doc["province"] == "河南"
    assert doc["source_name"].startswith("Gaokao-Compass-11M")
    assert "2025｜本科批｜物理类：最低分 601" in doc["content"]
    assert "2024｜本科一批｜理科：最低分 586" in doc["content"]
    assert "仅做聚合、不推算" in doc["content"]


def test_import_dir_idempotent_and_validation() -> None:
    out_dir = _work / "packs"
    # 追加一个缺来源的坏文档 + 一个超长正文（验证自动切块）
    pack_path = out_dir / "pack-test-extra.json"
    long_content = "平行志愿投档规则说明。" + "具体投档比例与单科要求以当年招生章程为准。" * 60  # ~1270 字，须切 ≥2 块
    pack_path.write_text(json.dumps({
        "pack": "test-extra",
        "docs": [
            {"title": "缺来源文档", "source_name": "", "source_url": "", "year": 0,
             "content": "不应入库"},
            {"title": "长文自动切块测试", "source_name": "河南省教育考试院",
             "source_url": "https://www.haeea.cn/test", "year": 2026,
             "doc_type": "政策", "province": "河南", "content": long_content},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    with SessionLocal() as db:
        admin = db.scalars(select(AdminUser).order_by(AdminUser.id)).first()
        report = corpus_packs.import_dir(db, out_dir, admin)

    # 坏文档记失败不中断；长文切块入库
    assert report["failed"] == 1, report
    assert report["imported"] == 5, report  # 4 个 build 包各 1 篇 + 长文 1 篇
    with SessionLocal() as db:
        bad = db.query(KnowledgeDoc).filter(KnowledgeDoc.title == "缺来源文档").count()
        assert bad == 0, "缺来源文档不应入库"

        long_doc = db.query(KnowledgeDoc).filter(
            KnowledgeDoc.title == "长文自动切块测试").one()
        chunk_rows = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.doc_id == long_doc.id).all()
        assert len(chunk_rows) >= 2, "长文未自动切块"
        assert all(len(c.content) <= 800 for c in chunk_rows)
        assert "".join(c.content for c in chunk_rows).split() == long_content.split()

        # 途径说明入库后带 province/pathway 元数据（检索过滤维度）
        pathway_doc = db.query(KnowledgeDoc).filter(
            KnowledgeDoc.title == "升学途径说明：国家专项计划").one()
        p_chunk = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.doc_id == pathway_doc.id).one()
        assert p_chunk.pathway_id == "national-special"

    # 复跑 → 全部幂等 skip
    with SessionLocal() as db:
        admin = db.scalars(select(AdminUser).order_by(AdminUser.id)).first()
        report2 = corpus_packs.import_dir(db, out_dir, admin)
    assert report2["imported"] == 0, report2
    assert report2["skipped"] == report["imported"], (report2, report)  # 好文档全部幂等 skip
    assert report2["failed"] == 1  # 坏文档仍如实失败


def main() -> int:
    tests = [
        test_chunking_basic_properties,
        test_build_packs_structure,
        test_import_dir_idempotent_and_validation,
    ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{test.__name__}: {type(exc).__name__}: {exc}")
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"corpus packs tests: {len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

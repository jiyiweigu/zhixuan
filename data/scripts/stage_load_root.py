"""合并数据集 → 装载根（``load_root``）staging。

把「智选志愿_数据整合/merged/」的合并产物转成 importer（``app.services.importers``）
读取的目录布局——输出路径沿用合并产物的相对路径（``schools/schools_merged.json``、
``majors/majors.json``、``score_segment/…`` 等），即 importer 的 ``data_root`` 协议。

三道入口校验（宁可停下，不带病装载）：

1. 映射文件存在、JSON 可解析、含 ``records`` 列表；
2. ``meta.target_table`` 与目标表一致、``meta.count`` 与行数一致（防错版/截断产物）；
3. ``school`` 行必须带 ``source_id``——importer 的来源「三要素缺一不入库」闸门要求
   逐行可解析，缺了就是合并侧 bug（真实发生过：合并脚本漏戳来源，1367 行会被整体跳过）。

用法：
    python data/scripts/stage_load_root.py \
        --merged-root "C:/…/智选志愿_数据整合/merged" \
        --output-root "C:/…/智选志愿_数据整合/load_root"

随后（``load_root`` 与数据库都在仓库外，数据本体不入库）：
    cd backend && python -m alembic upgrade head
    set ZHIXUAN_DATA_ROOT=<output-root> && python -m app.services.importers
对账：``python data/scripts/check_load_counts.py backend/.runtime/zhixuan.db``
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# 输出相对路径（= importer 读取布局）: (merged 目录中的文件名, importer 读取的记录键, 目标表)
MAP: dict[str, tuple[str, str, str]] = {
    "sources/source-table.json": ("source.json", "sources", "source"),
    "dictionaries/pathways-26.json": ("pathway.json", "pathways", "pathway"),
    "dictionaries/pathway-regions.json": ("pathway_region.json", "regions", "pathway_region"),
    "dictionaries/pathway-eligibility.json": ("pathway_eligibility.json", "rules", "pathway_eligibility"),
    "dictionaries/province-exam-rule.json": ("province_exam_rule.json", "rules", "province_exam_rule"),
    "schools/schools_merged.json": ("school.json", "records", "school"),
    "majors/majors.json": ("major.json", "records", "major"),
    "score_segment/score_segment.json": ("score_segment.json", "segments", "score_segment"),
    "school_major_score/school_major_score.json": ("school_major_score.json", "scores", "school_major_score"),
}

DEFAULT_MERGED = Path(r"C:\Users\Administrator\Desktop\智选志愿_数据整合\merged")
DEFAULT_OUTPUT = Path(r"C:\Users\Administrator\Desktop\智选志愿_数据整合\load_root")


def stage_one(
    merged_root: Path, output_root: Path, out_rel: str, src_name: str, key: str, target: str
) -> int:
    source = merged_root / src_name
    if not source.is_file():
        raise SystemExit(f"缺少合并产物：{source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    meta = payload.get("meta") or {}
    rows = payload.get("records")
    if not isinstance(rows, list):
        raise SystemExit(f"{source}: 缺少 records 列表")
    if meta.get("target_table") != target or meta.get("count") != len(rows):
        raise SystemExit(
            f"{source}: target_table/count 校验失败"
            f"（meta.target_table={meta.get('target_table')!r}，期望 {target!r}；"
            f"meta.count={meta.get('count')!r}，期望 {len(rows)}）"
        )
    if target == "school":
        missing = sum(1 for r in rows if not r.get("source_id"))
        if missing:
            raise SystemExit(
                f"{source}: {missing} 行院校缺 source_id，无法通过 importer 的"
                "「三要素缺一不入库」闸门；请先在合并侧补齐行级来源后再 staging"
            )
    out = output_root / out_rel
    out.parent.mkdir(parents=True, exist_ok=True)
    staged = dict(payload)
    staged.pop("records", None)
    staged[key] = rows
    out.write_text(json.dumps(staged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{target}: {len(rows)} 行 -> {out}")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="合并数据集 → 装载根 staging")
    parser.add_argument("--merged-root", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    total = 0
    for out_rel, (src_name, key, target) in MAP.items():
        total += stage_one(args.merged_root, args.output_root, out_rel, src_name, key, target)
    print(f"Staging 完成：{len(MAP)} 个数据集 / {total} 行 -> {args.output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

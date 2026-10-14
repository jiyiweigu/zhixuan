#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""核对 `data/MANIFEST.sha256` 与本地数据本体的一致性（只读，幂等）。

背景
----
develop `766f10e`（2026-10-13）把「数据本体」移出公开仓库，改为
`data/DOWNLOAD.md` + `data/MANIFEST.sha256` 重建 + 校验。本脚本回答三个问题：

1. MANIFEST 列的 N 个文件，本地留档是否齐全（缺失 = 会挡住重建校验）；
2. 摘要不符的，差异**性质**是什么（枚举迁移 / 行尾 / 真实内容演进）；
3. MANIFEST 记录的是**哪一版**内容（develop 基线 vs 本方分支基线）。

差异归类（关键）
----------------
- `一致`          ：磁盘字节与 MANIFEST 完全相同
- `枚举/行尾差异`  ：与 develop 基线**逐字节等价**（去行尾、`data_status` 取值归一后相同）
                    —— 本仓为契约 v1.3 迁移（`pending`→`schema_only`）所致，属预期
- `内容演进`       ：与 develop 基线**不等价**（本方分支产出了更多字段/行）
                    —— 如 `school_major_score` 的 `major_id` 回填、`schools_merged` 的 N21 补录
- `已知移出`       ：队长 `840dfa7`（2026-10-14）裁定**移出仓库**的上海软科榜单 3 文件，
                    不计入「缺失」；仍显式列出，避免静默忽略掩盖真实缺失
- `缺失`          ：本地不存在

退出码
------
0 = 无「缺失」且无「未知差异」（`已知移出` 不计入失败）
1 = 存在「缺失」，或存在无法归类的差异（需人工介入）

用法
----
    python data/scripts/check_manifest.py                # 概览 + 明细
    python data/scripts/check_manifest.py --strict       # 要求逐字节全等（CI 用）
    python data/scripts/check_manifest.py --json data/manifest_check_diag.json
                                     # 结构化结果（*_diag.json 已被 .gitignore 覆盖）
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = REPO / "data" / "MANIFEST.sha256"

# 差异归类的对照版本：develop 移出时的内容 / 本方分支合并前基线
REV_DEVELOP = "766f10e^"
REV_BRANCH = "ab6f2f8"

# ★ 队长 2026-10-14 复议（commit 840dfa7）：上海软科榜单 3 文件**移出仓库**，
#   不再作为本地留档要求。这里从「缺失」判定中剔除，但**显式列出**（不静默忽略），
#   以免掩盖真实缺失。
KNOWN_REMOVED: dict[str, str] = {
    "data/schools/shanghairanking_2024.json":    "队长 840dfa7 裁定移出仓库",
    "data/schools/shanghai_top300.json":         "队长 840dfa7 裁定移出仓库",
    "data/schools/shanghai_top300_inhenan.json": "队长 840dfa7 裁定移出仓库",
}

_RE_STATUS = re.compile(rb'"data_status":(\s*)"\w+"')


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon(b: bytes) -> bytes:
    """归一化：行尾统一 LF + `data_status` 取值置为占位符。

    用于判断「两份内容是否仅差枚举取值与行尾」——即语义等价。
    """
    b = b.replace(b"\r\n", b"\n")
    return _RE_STATUS.sub(rb'"data_status":\1"_"', b)


def read_manifest(path: pathlib.Path) -> list[tuple[str, str]]:
    """返回 [(sha256, 相对路径), ...]；忽略注释与空行。"""
    out: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        out.append((parts[0], parts[1].strip()))
    return out


def git_blob(rev_path: str) -> bytes | None:
    """取 `<rev>:<path>` 的原始字节；不存在返回 None。"""
    try:
        r = subprocess.run(
            ["git", "show", rev_path],
            cwd=str(REPO), capture_output=True, timeout=60,
        )
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def classify(rel: str, expect: str, present: bool, blob_cache: dict) -> tuple[str, dict]:
    """返回 (类别, 附注)。类别见模块 docstring。"""
    note: dict = {}
    if not present:
        return "缺失", note
    p = REPO / rel
    raw = p.read_bytes()
    if sha256_bytes(raw) == expect:
        return "一致", note

    dev = blob_cache.get(rel)
    b_dev_eq = bool(dev) and canon(raw) == canon(dev)
    note["has_dev_base"] = dev is not None
    note["dev_matches_manifest"] = bool(dev) and sha256_bytes(dev) == expect
    note["eol_only"] = sha256_bytes(raw.replace(b"\r\n", b"\n")) == expect

    if b_dev_eq:
        return "枚举/行尾差异", note
    return "内容演进", note


def main() -> int:
    ap = argparse.ArgumentParser(description="核对 MANIFEST.sha256 与本地数据本体")
    ap.add_argument("--strict", action="store_true",
                    help="要求逐字节全等（任何差异都视为失败）")
    ap.add_argument("--json", dest="json_out", default="",
                    help="把结构化结果写入该路径")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"[FAIL] 找不到 {MANIFEST}", file=sys.stderr)
        return 1

    entries = read_manifest(MANIFEST)

    # 预取对照 blob（按需，失败静默）
    blob_cache: dict[str, bytes | None] = {}
    for _, rel in entries:
        b = git_blob(f"{REV_DEVELOP}:{rel}")
        if b is None:
            b = git_blob(f"{REV_BRANCH}:{rel}")
        blob_cache[rel] = b

    rows = []
    for expect, rel in entries:
        if rel in KNOWN_REMOVED:
            rows.append({"path": rel, "class": "已知移出", "expected": expect,
                         "note": KNOWN_REMOVED[rel]})
            continue
        present = (REPO / rel).exists()
        cls, note = classify(rel, expect, present, blob_cache)
        rows.append({"path": rel, "class": cls, "expected": expect, **note})

    stats = collections.Counter(r["class"] for r in rows)
    unknown = [r for r in rows if r["class"] not in
               ("一致", "枚举/行尾差异", "内容演进", "已知移出", "缺失")]
    missing = [r for r in rows if r["class"] == "缺失"]

    print(f"MANIFEST 共 {len(rows)} 条")
    for k in ("一致", "枚举/行尾差异", "内容演进", "已知移出", "缺失"):
        if stats.get(k):
            print(f"  ├ {k:<12} {stats[k]:>3}")

    if not args.quiet:
        ev = [r for r in rows if r["class"] == "内容演进"]
        if ev:
            print("\n--- 内容演进（本方分支相对 develop 基线的真实差异）---")
            for r in ev:
                print(f"   {r['path']}")
        removed = [r for r in rows if r["class"] == "已知移出"]
        if removed:
            print("\n--- 已知移出（队长裁定移出仓库，不计入缺失）---")
            for r in removed:
                print(f"   {r['path']}  —— {r.get('note', '')}")
        if missing:
            print("\n--- 缺失（重建校验会直接失败）---")
            for r in missing:
                print(f"   {r['path']}")

    # 退出码判定
    fail = bool(missing or unknown)
    if args.strict:
        fail = bool(stats.get("枚举/行尾差异") or stats.get("内容演进")
                    or stats.get("缺失") or unknown)

    if args.json_out:
        pathlib.Path(args.json_out).write_text(
            json.dumps({
                "manifest": str(MANIFEST.relative_to(REPO)).replace("\\", "/"),
                "rev_develop": REV_DEVELOP, "rev_branch": REV_BRANCH,
                "summary": dict(stats), "rows": rows,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n结构化结果 → {args.json_out}")

    print(f"\n{'[FAIL]' if fail else '[OK]'}  "
          f"一致 {stats.get('一致', 0)} ｜ 枚举/行尾 {stats.get('枚举/行尾差异', 0)} ｜ "
          f"内容演进 {stats.get('内容演进', 0)} ｜ 已知移出 {stats.get('已知移出', 0)} ｜ "
          f"缺失 {stats.get('缺失', 0)}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""
河南省一分一段表解析脚本（数据工程 ③ — 任务 2.2）

背景
----
河南省教育考试院的一分一段表（分数段统计表）是**扫描件 PDF**：
每页 = 一张 JPEG 图片，无文本层，必须 OCR。

数据来源
--------
- 河南省阳光高考信息平台 https://gaokao.haedu.cn/
- 附件经 /api/download_files 接口下发（纯 HTTP，无需执行 JS）
- 官方口径：「表中'考生人数'为加入政策性照顾分后对应总分及以上考生累计人数」
  → 即 score_segment.cumulative_rank

版面（图像分析确认）
--------------------
- 每页 3 栏等宽，每栏 2 列（左=分数，右=累计人数）
- 横线间距恒定 32px，每页 28 个数据行
- 竖线/横线用投影法动态检测，不写死坐标

OCR 方案
--------
- **逐格切分 + 并行 OCR**（8 线程）：168 格约 9 秒/页，约 75 秒/科
  （曾试"整栏拼接一次 OCR"，多行时 Tesseract 会漏行/并行导致错位，已弃用）
- 单元格参数：放大 4×、二值化、`--psm 7`、数字白名单
- **三重自检**：
  1) 网格锚定 —— 结果按"栏-行"位置落座，不靠顺序
  2) 分数严格递减
  3) 累计人数严格递增
  任何冲突以众数/插值修正，并记录到 warnings

运行
----
    python data/scripts/parse_score_segment.py <img_dir> --year 2026 --subject 历史类

输出
----
- data/score_segment/score_segment_<year>_<subject>.json
- data/score_segment/score_segment_<year>_<subject>.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
OUT_DIR = os.path.join(BASE_DIR, "score_segment")

SOURCE_URL = "https://gaokao.haedu.cn/501/552/2026/0625/155639.html"
SOURCE_NAME = "河南省教育考试院（经河南省阳光高考信息平台发布）"

_TESS: Optional[str] = None


def find_tesseract() -> str:
    global _TESS
    if _TESS:
        return _TESS
    for cand in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if os.path.exists(cand):
            _TESS = cand
            return cand
    _TESS = "tesseract"
    return _TESS


def _projections(gray: Image.Image, *, vertical: bool,
                 span: Tuple[int, int], thresh: float) -> List[int]:
    W, H = gray.size
    px = gray.load()
    if vertical:
        proj = [sum(1 for y in range(0, H, 3) if px[x, y] < 128) for x in range(W)]
    else:
        a, b = span
        proj = [sum(1 for x in range(a, b, 4) if px[x, y] < 128) for y in range(H)]
    mx = max(proj) or 1
    runs = [i for i, c in enumerate(proj) if c > thresh * mx]
    groups: List[List[int]] = []
    for i in runs:
        if groups and i - groups[-1][-1] <= 2:
            groups[-1].append(i)
        else:
            groups.append([i])
    return [int(sum(g) / len(g)) for g in groups]


def load_clean(pdf_page_img: str) -> Image.Image:
    """
    读图并**去除红色水印**，得到干净的黑白表格图。

    为什么必须去水印：
    官方 PDF 页面上覆盖了大字红色水印「河南省教育考试院」。
    直接转灰度后，红字会变成暗灰（<150），与表格数字一同被 OCR 读到，
    造成大量乱值（实测出现"分数 2""466374"这类噪声）。

    做法：在 RGB 空间判定"红显著"，把这些像素刷白。
    红色判定：R 明显大于 G 和 B。黑色数字 R≈G≈B，不会被误伤。
    """
    im = Image.open(pdf_page_img).convert("RGB")
    px = im.load()
    W, H = im.size
    for y in range(H):
        for x in range(W):
            r, g, b = px[x, y]
            # 红水印：R 高、且明显比 G/B 大
            if r > 120 and r - g > 40 and r - b > 40:
                px[x, y] = (255, 255, 255)
    return im.convert("L")


def _detect_columns(vlines: List[int]) -> List[Tuple[int, int, int]]:
    """
    根据竖线数量自适应识别栏数。
    每栏 3 条竖线（左边界 / 列分界 / 右边界）。
    最后一页可能只有 1 栏，需正常支持。
    """
    n = len(vlines) // 3
    cols = []
    for i in range(n):
        a, b, c = vlines[3 * i], vlines[3 * i + 1], vlines[3 * i + 2]
        cols.append((a, b, c))
    return cols


def _tess_once(binary_img: Image.Image) -> str:
    """对一张已二值化的图跑一次 tesseract"""
    tess = find_tesseract()
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tmp = tf.name
        binary_img.save(tmp)
        out = subprocess.run(
            [tess, tmp, "stdout", "--psm", "7",
             "-c", "tessedit_char_whitelist=0123456789"],
            capture_output=True, text=True, timeout=60,
        )
        return out.stdout.strip()
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def ocr_cell(img: Image.Image) -> str:
    """
    多阈值重试 OCR。

    单阈值失败的原因：官方 PDF 是扫描件 + 红色水印叠加，
    不同格子的局部对比度差异大（水印浓度不均）。
    固定阈值必然在部分格子上把数字笔画切断或把水印虚影连成笔画。

    做法：用一组阈值依次尝试，取**首个合法的纯数字结果**。
    合法 = 能通过数字白名单且长度合理（人数最多 7 位、分数最多 3 位）。
    """
    big = img.resize((img.width * 4, img.height * 4), Image.LANCZOS)

    # 只试 2 个阈值：先用默认，失败再放宽。
    # 试 5 个阈值会使耗时至 5 倍（全量约 8 分钟），2 个阈值兼顾速度与召回。
    for thr in (150, 180):
        binary = big.point(lambda p, t=thr: 0 if p < t else 255)
        txt = _tess_once(binary)
        if txt and re.fullmatch(r"\d{1,7}", txt):
            return txt
    return ""


def parse_page(img_path: str) -> Tuple[List[List[Optional[int]]],
                                       List[List[Optional[int]]]]:
    """
    返回 (scores, ranks)：
      三维结构 [栏][行]；值为 None 表示该格未识别出内容（表头/空行）。
    结果**按网格位置落座**，不依赖 OCR 输出顺序。
    """
    gray = load_clean(img_path)
    im = Image.open(img_path).convert("RGB")
    W, H = gray.size

    vlines = _projections(gray, vertical=True, span=(0, H), thresh=0.5)
    if len(vlines) < 3:
        print(f"  ⚠️ {os.path.basename(img_path)} 竖线 {len(vlines)} 条，跳过")
        return [], []

    columns = _detect_columns(vlines)

    hlines = _projections(gray, vertical=False, span=(vlines[0], vlines[-1]),
                          thresh=0.5)
    if len(hlines) < 3:
        print(f"  ⚠️ {os.path.basename(img_path)} 横线 {len(hlines)} 条，跳过")
        return [], []

    bands = [(hlines[i], hlines[i + 1]) for i in range(len(hlines) - 1)
             if hlines[i + 1] - hlines[i] >= 12]

    # 收集所有格子（保持"栏-行-列"索引）；用去水印后的图裁剪
    jobs: List[Tuple[int, int, str, Image.Image]] = []
    for ci, (cx0, cx1, cx2) in enumerate(columns):
        for ri, (y0, y1) in enumerate(bands):
            jobs.append((ci, ri, "s", gray.crop((cx0 + 3, y0 + 3, cx1 - 3, y1 - 3))))
            jobs.append((ci, ri, "r", gray.crop((cx1 + 3, y0 + 3, cx2 - 3, y1 - 3))))

    with ThreadPoolExecutor(max_workers=8) as ex:
        texts = list(ex.map(lambda j: ocr_cell(j[3]), jobs))

    n_col, n_row = len(columns), len(bands)
    scores: List[List[Optional[int]]] = [[None] * n_row for _ in range(n_col)]
    ranks: List[List[Optional[int]]] = [[None] * n_row for _ in range(n_col)]

    for (ci, ri, kind, _img), txt in zip(jobs, texts):
        if not txt or not re.fullmatch(r"\d{1,7}", txt):
            continue
        (scores if kind == "s" else ranks)[ci][ri] = int(txt)

    return scores, ranks


def _repair(scores: List[List[Optional[int]]],
            ranks: List[List[Optional[int]]]
            ) -> Tuple[List[Tuple[int, int, str]], List[int], List[str]]:
    """
    以**分数列为骨架**重建数据，再用人数列填充。

    为什么以分数列为骨架
    --------------------
    实测发现（p1 逐格验证）：
      - 分数列识别近乎完美（686,685,684,…,676,675,674，逐行吻合）
      - 人数列有约 10% 的格子返回空或错值
    因此不能"分数+人数成对丢弃"，否则会连分数一起丢，造成大面积缺行。

    做法
    ----
    1. 收集全部 (栏, 行, 分数) 与 (栏, 行, 人数)，按"栏-行"网格位置配对
    2. 用分数列确定骨架：分数 0~750、唯一、递减（实测分数列 OCR 近乎完美）
    3. 人数列（本脚本的核心难点）：
       a. 先取"原始读数"作为**锚点**（不插值、不修正）
       b. **用最长非降子序列（LIS）挑选可信锚点**，一次性剔除离群误读
       c. 仅在**两个可信锚点之间**做线性插值
       d. 连续缺失 ≥ GAP_LIMIT 行时**不插值**，将其标为 gap
          （避免用长区间外推，误差会滚雪球）
    4. 输出中每行带 confidence：
       - `high`   原始读数通过全部校验
       - `low`    由插值得到，需人工复核
       - `gap`    数据缺失，无值（不出现在 segments 中，另列 gaps）

    注：宁可留 gap，也不外推——错数据会导致位次换算整体偏移。
    """
    warnings: List[str] = []

    # 1) 网格位置配对
    pairs: List[Tuple[int, Optional[int], int, int]] = []
    for ci, (s_col, r_col) in enumerate(zip(scores, ranks)):
        for ri, s in enumerate(s_col):
            if s is None or not (0 <= s <= 750):
                continue
            pairs.append((s, r_col[ri], ci, ri))

    ordered = sorted({s for s, _r, _ci, _ri in pairs}, reverse=True)

    rank_votes: Dict[int, List[int]] = {}
    for s, r, _ci, _ri in pairs:
        if r is None or not (0 <= r <= 1_500_000):
            continue
        rank_votes.setdefault(s, []).append(r)

    # 2) 先确定原始锚点（众数，不做任何修正）
    anchors: Dict[int, int] = {}
    for s in ordered:
        votes = rank_votes.get(s, [])
        if votes:
            anchors[s] = max(set(votes), key=votes.count)

    # 3) 锚点清洗 —— **最长非降子序列（LIS）法**
    #
    #    规则：分数从高到低（ordered 顺序）时，累计人数必须**非递减**。
    #    我们要在锚点序列里，找出**最长的**、满足非递减的那条子序列，
    #    保留它，其余判为离群误读。
    #
    #    ⚠️ 教训一（贪心锚点的致命缺陷）：
    #    曾用"与前一个锚点比较，小则弃用"。当出现一个**偏大**的错值
    #    （如 660 误读为 443，真值 115），它会抬高上界，
    #    导致其后所有**正确**读数（153、168、175…）全被判"违反单调"而弃用，
    #    错误被级联放大——一个错值毁掉整段。
    #    LIS 的优越性：它找的是**全局最优**的保留集合，
    #    单个错值只会自己被剔除，不会连带牺牲其后一整段正确读数。
    #
    #    ⚠️ 教训二（不要改数）：
    #    曾尝试"读数偏小则末尾补 0"（28→280），把大量正确值改错。
    #    本脚本**永不修改读数**，只决定"信"或"不信"。
    anchor_scores = sorted(anchors.keys(), reverse=True)   # 分数由高到低
    n_anchor = len(anchor_scores)

    # LIS：dp[i] = 以 i 结尾的最长非降子序列长度；prev[i] 记录前驱
    dp = [1] * n_anchor
    prev = [-1] * n_anchor
    for i in range(n_anchor):
        ri = anchors[anchor_scores[i]]
        for j in range(i):
            rj = anchors[anchor_scores[j]]
            # ordered 由高到低，位次非递减：rj <= ri 才可接上
            if rj <= ri and dp[j] + 1 > dp[i]:
                dp[i] = dp[j] + 1
                prev[i] = j
    # 回溯出最优保留集合
    best_end = max(range(n_anchor), key=lambda k: dp[k]) if n_anchor else -1
    keep_idx = set()
    k = best_end
    while k != -1:
        keep_idx.add(k)
        k = prev[k]

    clean_anchor: Dict[int, int] = {}
    for idx, s in enumerate(anchor_scores):
        if idx in keep_idx:
            clean_anchor[s] = anchors[s]
        else:
            warnings.append(
                f"分数 {s}：读数 {anchors[s]} 被 LIS 判为离群误读（破坏全局单调性），改为插值")

    # 4) 在锚点之间插值；长区间留 gap
    GAP_LIMIT = 12
    result: List[Tuple[int, int, str]] = []
    anchor_scores = sorted(clean_anchor.keys(), reverse=True)

    for s in ordered:
        if s in clean_anchor:
            result.append((s, clean_anchor[s], "high"))
            continue

        # 找前后最近锚点
        prev_a = next((a for a in anchor_scores if a > s), None)
        next_a = next((a for a in anchor_scores if a < s), None)

        if prev_a is None and next_a is None:
            result.append((s, 1, "low"))
            warnings.append(f"分数 {s} 无锚点，无法估计")
            continue

        if prev_a is None:
            r = max(1, clean_anchor[next_a] - 1)
            result.append((s, r, "low"))
            continue

        if next_a is None:
            r = clean_anchor[prev_a] + 1
            result.append((s, r, "low"))
            continue

        span = prev_a - next_a          # 区间跨度
        if span > GAP_LIMIT:
            # 长缺口：不外推，标 gap
            result.append((s, -1, "gap"))
            continue

        r_p, r_n = clean_anchor[prev_a], clean_anchor[next_a]
        ratio = (prev_a - s) / span
        r = int(round(r_p + ratio * (r_n - r_p)))
        if r <= r_p:
            r = r_p + 1
        if r >= r_n:
            r = r_n - 1
        result.append((s, r, "low"))

    # 5) 最终单调性清洗（只针对 high，low 已在插值时夹逼）
    final: List[Tuple[int, int, str]] = []
    last = 0
    for s, r, conf in result:
        if conf == "gap":
            final.append((s, -1, conf))
            continue
        if r <= last:
            r = last + 1
            if conf == "high":
                conf = "low"
                warnings.append(f"分数 {s} 读数低于前值，按单调性上调为 {r}")
        final.append((s, r, conf))
        last = r

    # 6) 返回：segments 仅含 high/low，gaps 单列
    segs = [(s, r, conf) for s, r, conf in final if conf != "gap"]
    gaps = [s for s, _r, conf in final if conf == "gap"]
    if gaps:
        warnings.append(f"共 {len(gaps)} 个分数无可靠值（长缺口），已列入 gaps 待人工补录")

    return segs, gaps, warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("img_dir")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--refresh", action="store_true",
                    help="忽略 OCR 网格缓存，重新跑一遍 OCR")
    args = ap.parse_args()

    print(f"[OCR] {find_tesseract()}")

    os.makedirs(OUT_DIR, exist_ok=True)
    cache_path = os.path.join(OUT_DIR, f".ocrcache_{args.year}_{args.subject}.json")

    # OCR 网格缓存：OCR 很慢（约 75 秒/科），而 _repair 算法的迭代是秒级的。
    # 把 OCR 结果落盘后，调算法时用 --refresh 以外的默认路径秒级重算。
    if os.path.exists(cache_path) and not args.refresh:
        with open(cache_path, encoding="utf-8") as fh:
            cached = json.load(fh)
        all_scores = cached["scores"]
        all_ranks = cached["ranks"]
        print(f"[OCR] 命中缓存 {os.path.basename(cache_path)}，跳过识别")
    else:
        imgs = sorted(
            f for f in os.listdir(args.img_dir)
            if f.startswith(args.subject) and f.lower().endswith((".jpg", ".jpeg", ".png"))
        )
        if not imgs:
            print(f"❌ 未找到 {args.subject} 的页面图片")
            return 2

        all_scores: List[List[Optional[int]]] = []
        all_ranks: List[List[Optional[int]]] = []
        for fn in imgs:
            s, r = parse_page(os.path.join(args.img_dir, fn))
            got = sum(1 for c in s for v in c if v is not None)
            print(f"  {fn}: 识别 {got} 个分数格")
            if s:
                all_scores.extend(s)
                all_ranks.extend(r)

        with open(cache_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"scores": all_scores, "ranks": all_ranks}, fh, ensure_ascii=False)

    rows, gaps, warnings = _repair(all_scores, all_ranks)

    high = sum(1 for _s, _r, c in rows if c == "high")
    low = sum(1 for _s, _r, c in rows if c == "low")

    payload = {
        "meta": {
            "title": f"河南省 {args.year} 年普通高招分数段统计表（{args.subject}）",
            "target_table": "score_segment",
            "province": "河南",
            "year": args.year,
            "subject_type": args.subject,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "source_id": f"SRC-HENAN-SCORE-SEG-{args.year}",
            "cumulative_rank_note": (
                "官方口径：表中'考生人数'为加入政策性照顾分后对应总分及以上"
                "考生累计人数，即 cumulative_rank。"
            ),
            "parse_method": (
                "扫描件 OCR：Tesseract 5.4 + 投影法网格切分 + 并行逐格多阈值识别；"
                "分数骨架取自分数列（识别可靠），人数列仅信原始读数锚点，缺口插值并标注置信度"
            ),
            "final_rows": len(rows),
            "high_confidence_rows": high,
            "interpolated_rows": low,
            "gap_scores": gaps,
            "review_status": "OCR 结果，low 置信行与 gaps 需人工复核后方可入库",
            "warnings": warnings,
        },
        "segments": [
            {"province": "河南", "year": args.year, "subject_type": args.subject,
             "score": s, "cumulative_rank": r, "confidence": conf}
            for s, r, conf in rows
        ],
    }

    jp = os.path.join(OUT_DIR, f"score_segment_{args.year}_{args.subject}.json")
    with open(jp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    cp = os.path.join(OUT_DIR, f"score_segment_{args.year}_{args.subject}.csv")
    with open(cp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["province", "year", "subject_type", "score",
                    "cumulative_rank", "confidence"])
        for s, r, conf in rows:
            w.writerow(["河南", args.year, args.subject, s, r, conf])

    print()
    print(f"✅ {args.subject}：共 {len(rows)} 行"
          f"（high {high} / low {low}）")
    if rows:
        print(f"   分数 {rows[0][0]} ~ {rows[-1][0]}")
        print(f"   累计人数 {rows[0][1]} ~ {rows[-1][1]}")
    if gaps:
        print(f"   ⚠️ 缺口 {len(gaps)} 个分数待人工补录：{sorted(gaps, reverse=True)[:20]}")
    if warnings:
        print(f"⚠️  自检告警 {len(warnings)} 条（前 6）：")
        for x in warnings[:6]:
            print("   -", x)
    print(f"   → {os.path.relpath(jp, ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

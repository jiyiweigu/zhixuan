# -*- coding: utf-8 -*-
"""
一分一段表复核工作台生成器（数据工程 ③ — 任务 2.2 配套）

用途
----
OCR 结果无法做到 100% 准确（官方只发布扫描件 + 红色水印）。
本脚本把「原图」与「解析结果」并排放进一个 HTML 页面，
供人工快速比对复核，把复核成本降到最低。

输出
----
data/score_segment/review_<year>_<subject>.html

用法
----
    python data/scripts/build_review_page.py --year 2026 --subject 历史类
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "score_segment")
IMG_DIR = os.path.join(BASE_DIR, "samples", "raw", "imgs")


def img_to_b64(path: str) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--subject", required=True)
    args = ap.parse_args()

    jp = os.path.join(OUT_DIR, f"score_segment_{args.year}_{args.subject}.json")
    if not os.path.exists(jp):
        print(f"❌ 未找到 {jp}")
        return 2

    with open(jp, encoding="utf-8") as fh:
        doc = json.load(fh)

    segs = doc["segments"]
    meta = doc["meta"]

    # 统计
    high = [s for s in segs if s["confidence"] == "high"]
    low = [s for s in segs if s["confidence"] == "low"]

    # 原图
    pages = sorted(
        f for f in os.listdir(IMG_DIR)
        if f.startswith(args.subject) and f.lower().endswith(".jpg")
    )
    imgs_html = []
    for p in pages:
        b64 = img_to_b64(os.path.join(IMG_DIR, p))
        imgs_html.append(
            f'<figure><img src="data:image/jpeg;base64,{b64}" alt="{p}">'
            f'<figcaption>{p}</figcaption></figure>'
        )

    # 数据行
    rows_html = []
    for s in segs:
        cls = "high" if s["confidence"] == "high" else "low"
        rows_html.append(
            f'<tr class="{cls}"><td>{s["score"]}</td>'
            f'<td>{s["cumulative_rank"]}</td>'
            f'<td>{"可信" if cls == "high" else "插值"}</td></tr>'
        )

    gaps = meta.get("gap_scores") or []
    gap_html = "、".join(str(g) for g in sorted(gaps, reverse=True))

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>一分一段表复核 · {args.year} {args.subject}</title>
<style>
  :root {{
    --bg:#ffffff; --fg:#1f2328; --muted:#656d76; --line:#d0d7de;
    --high:#1a7f37; --low:#9a6700; --warn:#bc4c00; --panel:#f6f8fa;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
         background:var(--bg); color:var(--fg); }}
  header {{ padding:16px 24px; border-bottom:1px solid var(--line);
            position:sticky; top:0; background:var(--bg); z-index:10; }}
  h1 {{ margin:0 0 8px; font-size:18px; }}
  .stats span {{ display:inline-block; margin-right:16px; color:var(--muted); }}
  .stats b {{ color:var(--fg); }}
  main {{ display:grid; grid-template-columns: 1fr 380px; gap:0; }}
  .viewer {{ padding:20px; overflow-y:auto; height:calc(100vh - 90px); }}
  .sidebar {{ border-left:1px solid var(--line); overflow-y:auto;
              height:calc(100vh - 90px); background:var(--panel); }}
  figure {{ margin:0 0 24px; }}
  img {{ width:100%; border:1px solid var(--line); border-radius:6px; }}
  figcaption {{ color:var(--muted); font-size:12px; margin-top:6px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ padding:6px 10px; border-bottom:1px solid var(--line); text-align:right; }}
  th:last-child,td:last-child {{ text-align:center; }}
  thead th {{ position:sticky; top:0; background:var(--panel); }}
  tr.high td:last-child {{ color:var(--high); }}
  tr.low td:last-child {{ color:var(--low); }}
  tr.low {{ background:#fff8e5; }}
  .notice {{ background:#fff8e5; border-left:3px solid var(--warn);
             padding:10px 14px; margin:16px 0; border-radius:4px; font-size:13px; }}
  .gaps {{ font-size:12px; color:var(--muted); word-break:break-all; }}
</style>
</head>
<body>
<header>
  <h1>一分一段表复核 · {args.year} 年河南 {args.subject}</h1>
  <div class="stats">
    <span>总行数 <b>{len(segs)}</b></span>
    <span>可信行 <b>{len(high)}</b></span>
    <span>插值行 <b>{len(low)}</b></span>
    <span>缺口 <b>{len(gaps)}</b></span>
  </div>
</header>
<main>
  <div class="viewer">
    <div class="notice">
      <b>复核方法</b>：左侧是官方原始扫描页，右侧是解析结果。
      黄色行为插值（非直接读数），请优先核对。
      如发现错误，直接在
      <code>data/score_segment/score_segment_{args.year}_{args.subject}.json</code>
      修改 <code>cumulative_rank</code> 并把 <code>confidence</code> 改为 <code>high</code>。
    </div>
    {''.join(imgs_html)}
  </div>
  <div class="sidebar">
    <table>
      <thead><tr><th>分数</th><th>累计人数</th><th>状态</th></tr></thead>
      <tbody>{''.join(rows_html)}</tbody>
    </table>
    {'<div class="notice"><b>缺口分数（无值）</b><div class="gaps">' + gap_html + '</div></div>' if gaps else ''}
  </div>
</main>
</body>
</html>
"""

    op = os.path.join(OUT_DIR, f"review_{args.year}_{args.subject}.html")
    with open(op, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    print(f"✅ 复核页已生成：{os.path.relpath(op, BASE_DIR)}")
    print(f"   {len(pages)} 页原图 / {len(segs)} 行数据 / {len(gaps)} 个缺口")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
专项计划录取分采集器（D-4）→ pathway_score。

背景（为什么专项分要单独采、单独存）：
  - 2025 起河南实行新高考，国家专项/地方专项/高校专项**并入普通本科批**，
    以独立的「院校专业组」投档（如「第301组(国家专项计划)」）；
  - 专项计划只面向**资格考生**（县名单 + 户籍/学籍），其录取分与普通批
    差距显著（可低 10–60 分），是产品「升学途径」推荐的核心判据，
    因此不能混入 school_major_score，必须落到 pathway_score。

数据源（多层，均登记来源三要素）：
  1. 高校招生网发布的《XXXX年在豫招生各批次及各专业组录取分数一览表》
     —— 静态 HTML 表格，逐行含「批次及专业组 / 科类 / 最低分 / 位次」，
        专项组明确标注（如「本科批：第301组 ( 国家专项计划 )」）。
        例：河南财经政法大学 https://zs.huel.edu.cn/info/1357/3119.htm
  2. 政府门户 / 官方新闻公布的专项录取分
     —— 纯文本，形如「国家专项历史类最低录取分598，最高录取分619」。
        例：河南省人民政府门户 https://m.henan.gov.cn/2025/07-22/3182795.html
  3. seeds/pathway_scores.json —— 在线源不可用时的**兜底**（人工核验的官方数值）

字段对齐 db/schema.sql 的 pathway_score 表：
  pathway_name, school_name, school_code, province, year, batch,
  subject_type, group_code, group_name, min_score, max_score, min_rank,
  admitted_num, source_name, source_url
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .base import (PARSER, RawRecord, fetch, normalize_batch, normalize_subject,
                   parse_html, save_raw, to_int)

logger = logging.getLogger(__name__)

SEEDS_PATH = Path(__file__).resolve().parents[1] / "seeds" / "pathway_scores.json"

# 专项关键字的三种写法 → pathway 字典中的规范名称
_PATHWAY_NAMES = (
    ("国家专项", "国家专项计划"),
    ("地方专项", "地方专项计划"),
    ("高校专项", "高校专项计划"),
)
_SPECIAL_RE = re.compile(r"国家专项|地方专项|高校专项")
# 专业组代码：「第301组」「第 302 组」「301组」
_GROUP_CODE_RE = re.compile(r"第\s*(\d{1,4})\s*组")
_SUBJECT_RE = re.compile(r"^(历史类|物理类|文科|理科|综合|文史|理工|文|理)$")


# ---------------------------------------------------------------------------
# 数据源注册表（新增院校只需在此追加一行）
# ---------------------------------------------------------------------------
REGISTRY: list[dict] = [
    {
        "school_name": "河南财经政法大学",
        "school_code": "10484",
        "year": 2025,
        "kind": "html_table",
        "url": "https://zs.huel.edu.cn/info/1357/3119.htm",
        "source_name": "河南财经政法大学招生信息网（在豫分专业组录取分）",
    },
    {
        "school_name": "郑州大学",
        "school_code": "10459",
        "year": 2025,
        "kind": "gov_text",
        "url": "https://m.henan.gov.cn/2025/07-22/3182795.html",
        "source_name": "河南省人民政府门户网站（郑大2025录取分公布）",
    },
]


def pathway_name_of(text: str) -> str | None:
    """从含专项字样的文本中识别规范途径名；识别不出返回 None。"""
    for kw, name in _PATHWAY_NAMES:
        if kw in (text or ""):
            return name
    return None


def _to_float(s: str | None) -> float | None:
    s = (s or "").replace(",", "").replace("，", "").strip()
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    v = float(s)
    return v


# ---------------------------------------------------------------------------
# 源 1：高校招生网「各批次及各专业组录取分数」静态表格
# ---------------------------------------------------------------------------
def _row_cells(tr) -> list[str]:
    cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))
             for c in tr.find_all(["td", "th"])]
    return [c for c in cells if c]


def parse_group_table(soup: BeautifulSoup) -> list[dict]:
    """解析「批次及专业组 / 科类 / 最低分 / 位次」表（含 rowspan 合并首列）。

    表格首列常以 rowspan 合并：同一专业组的多个科类只在第一行出现组名，
    后续行首列为「历史类/物理类」。因此需要**沿用上一个组名**（carry-forward）。
    返回全部数据行（不做专项筛选），字段：
        batch, group_code, group_name, subject_type, min_score, max_score, min_rank
    """
    rows: list[dict] = []
    for tb in soup.find_all("table"):
        head = tb.get_text(" ", strip=True)
        if "批次及专业组" not in head or "科类" not in head:
            continue

        last_group: str | None = None
        for tr in tb.find_all("tr"):
            cells = _row_cells(tr)
            if len(cells) < 3:
                continue
            # 表头行
            if "批次及专业组" in cells[0] and "科类" in " ".join(cells):
                continue

            si = next((i for i, c in enumerate(cells)
                       if _SUBJECT_RE.match(c.replace(" ", ""))), None)
            if si is None:
                continue

            group_text = " ".join(cells[:si]).strip()
            if group_text:
                last_group = group_text
            elif not last_group:
                continue
            group = group_text or last_group

            subject = normalize_subject(cells[si])
            if not subject:
                continue

            after = cells[si + 1:]
            # 列序：最低分 | 位次 | 省控线 | 备注
            min_score = _to_float(after[0]) if after else None
            min_rank = to_int(after[1]) if len(after) > 1 else None

            m = _GROUP_CODE_RE.search(group)
            batch_src = group.split("：")[0].strip() if "：" in group else ""
            rows.append({
                "batch": normalize_batch(batch_src) or None,
                "group_code": m.group(1) if m else None,
                "group_name": re.sub(r"\s+", "", group),
                "subject_type": subject,
                "min_score": min_score,
                "max_score": None,
                "min_rank": min_rank,
            })
    return rows


def collect_from_table(cfg: dict, batch_no: str) -> list[RawRecord]:
    r = fetch(cfg["url"])
    r.encoding = r.encoding or "utf-8"
    save_raw(cfg["url"], r.content, "html")
    soup = parse_html(r.text)

    records: list[RawRecord] = []
    seen: set[tuple] = set()
    for i, row in enumerate(parse_group_table(soup), start=1):
        group = row["group_name"] or ""
        if not _SPECIAL_RE.search(group):
            continue                       # 只要专项专业组
        pname = pathway_name_of(group)
        if not pname:
            continue
        # 同一页面常有桌面/移动多份相同表格，按业务键去重
        key = (pname, row.get("group_code"), row["subject_type"],
               row["min_score"], row.get("min_rank"))
        if key in seen:
            continue
        seen.add(key)
        records.append(RawRecord(
            data={
                "pathway_name": pname,
                "school_name": cfg["school_name"],
                "school_code": cfg.get("school_code"),
                "province": "河南",
                "year": cfg["year"],
                "batch": row["batch"],
                "subject_type": row["subject_type"],
                "group_code": row["group_code"],
                "group_name": row["group_name"],
                "min_score": row["min_score"],
                "max_score": row["max_score"],
                "min_rank": row["min_rank"],
                "admitted_num": None,
            },
            source_name=cfg["source_name"],
            source_url=cfg["url"],
            year=cfg["year"],
            doc_type="pathway_score",
            batch_no=batch_no,
            row_no=i,
        ))
    logger.info("  %s: %d 条专项专业组", cfg["school_name"], len(records))
    return records


# ---------------------------------------------------------------------------
# 源 2：政府门户 / 官方新闻（纯文本）
# ---------------------------------------------------------------------------
# 「国家专项历史类最低录取分598，最高录取分619；物理类最低录取分616，最高录取分642。」
# 注意：同一个专项的两个科类之间用「；」分隔，因此段结束只能按「下一个专项」或「。」判定，
# 不能按「；」截断，否则会丢掉物理类那一半。
_SEG_RE = re.compile(
    r"(国家专项|地方专项|高校专项).*?"
    r"(?=(?:国家专项|地方专项|高校专项)|。|$)",
    re.S,
)
_SUBJ_SCORE_RE = re.compile(
    r"(历史类|物理类|文科|理科)[^0-9]{0,14}?"
    r"最低录取分\s*(\d{2,3})"
    r"(?:[^0-9]{0,14}?最高录取分\s*(\d{2,3}))?"
)


def parse_gov_text(text: str) -> list[dict]:
    """从政府门户/官方新闻文本中抽取专项录取分（仅最低/最高分）。"""
    rows: list[dict] = []
    for seg_m in _SEG_RE.finditer(text or ""):
        pname = pathway_name_of(seg_m.group(1))
        if not pname:
            continue
        seg = seg_m.group(0)
        for sm in _SUBJ_SCORE_RE.finditer(seg):
            subject = normalize_subject(sm.group(1))
            if not subject:
                continue
            rows.append({
                "pathway_name": pname,
                "subject_type": subject,
                "min_score": float(sm.group(2)),
                "max_score": float(sm.group(3)) if sm.group(3) else None,
                "min_rank": None,
                "batch": None,
                "group_code": None,
                "group_name": None,
            })
    return rows


def collect_from_gov_text(cfg: dict, batch_no: str) -> list[RawRecord]:
    r = fetch(cfg["url"])
    r.encoding = r.encoding or "utf-8"
    save_raw(cfg["url"], r.content, "txt")
    text = re.sub(r"<[^>]+>", " ", r.text)

    records: list[RawRecord] = []
    for i, row in enumerate(parse_gov_text(text), start=1):
        records.append(RawRecord(
            data={
                "pathway_name": row["pathway_name"],
                "school_name": cfg["school_name"],
                "school_code": cfg.get("school_code"),
                "province": "河南",
                "year": cfg["year"],
                "batch": row["batch"],
                "subject_type": row["subject_type"],
                "group_code": row["group_code"],
                "group_name": row["group_name"],
                "min_score": row["min_score"],
                "max_score": row["max_score"],
                "min_rank": row["min_rank"],
                "admitted_num": None,
            },
            source_name=cfg["source_name"],
            source_url=cfg["url"],
            year=cfg["year"],
            doc_type="pathway_score",
            batch_no=batch_no,
            row_no=i,
        ))
    logger.info("  %s: %d 条专项分（官方文本）", cfg["school_name"], len(records))
    return records


# ---------------------------------------------------------------------------
# 源 3：种子兜底（人工核验的官方数值）
# ---------------------------------------------------------------------------
def collect_from_seeds(batch_no: str) -> list[RawRecord]:
    if not SEEDS_PATH.exists():
        logger.warning("pathway_score seeds not found: %s", SEEDS_PATH)
        return []
    data = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    records: list[RawRecord] = []
    for i, item in enumerate(data, start=1):
        records.append(RawRecord(
            data={
                "pathway_name": item["pathway_name"],
                "school_name": item.get("school_name", ""),
                "school_code": item.get("school_code"),
                "province": "河南",
                "year": item["year"],
                "batch": item.get("batch"),
                "subject_type": item["subject_type"],
                "group_code": item.get("group_code"),
                "group_name": item.get("group_name"),
                "min_score": item.get("min_score"),
                "max_score": item.get("max_score"),
                "min_rank": item.get("min_rank"),
                "admitted_num": item.get("admitted_num"),
            },
            source_name=item["source_name"],
            source_url=item["source_url"],
            year=item["year"],
            doc_type="pathway_score",
            batch_no=batch_no,
            row_no=i,
        ))
    logger.info("pathway_score(seed) -> %d rows", len(records))
    return records


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def collect_all(batch_no: str, limit: int | None = None) -> list[RawRecord]:
    """采集 D-4：逐源抓取；全部在线源失败时回退种子。"""
    records: list[RawRecord] = []
    targets = REGISTRY[:limit] if limit else REGISTRY
    for cfg in targets:
        try:
            if cfg["kind"] == "html_table":
                records.extend(collect_from_table(cfg, batch_no))
            else:
                records.extend(collect_from_gov_text(cfg, batch_no))
        except Exception as e:                                  # noqa: BLE001
            logger.error("pathway_score 源失败 %s: %s", cfg["url"], e)

    if not records:
        logger.warning("专项录取分在线源均为空，回退种子数据")
        records = collect_from_seeds(batch_no)

    for r in records:
        if not r.batch_no:
            r.batch_no = batch_no
    return records

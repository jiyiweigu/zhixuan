"""
江西采集 · 各模块采集器（对应爬取清单 A1–A8 / B1–B8）。

每个采集器的 docstring 说明：**数据来源 / 目标 URL / 页面解析方式**。
统一返回 list[validators.Record]（带来源三要素）。
所有采集器均支持 `offline=True`（不联网，改用 seeds/benchmarks），
以保证在无网络/被墙时可运行并产出可核验结果。
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import config, parsers, seeds
from .fetcher import Fetcher
from .validators import Record

logger = logging.getLogger("jx.collectors")

YEAR_RE = re.compile(r"(20\d{2})\s*年")


def _rec(data: dict, *, source_name: str, source_url: str, year: int,
         doc_type: str, row_no: int = 0) -> Record:
    return Record(data=data, source_name=source_name, source_url=source_url,
                  year=year, doc_type=doc_type, row_no=row_no)


def _year_from(text: str, default: int = 2025) -> int:
    m = YEAR_RE.search(text or "")
    return int(m.group(1)) if m else default


# ===========================================================================
# A1 · 批次录取控制分数线（省控线）
#   来源：中国教育在线·掌上高考江西栏目 / 江西省教育考试院公示公告
#   解析：① 表格 table tr；② 正文正则（历史类本科线463 / 本科批 历史类 463分）
# ===========================================================================
_BATCH_LINE_PATTERNS = [
    # 形式：历史类本科线463、物理类本科线448 / 历史类特招线532（科类在前）
    re.compile(r"(历史类|物理类|文史类|理工类)[^\d）]{0,12}?"
               r"(本科线|专科线|特招线|特殊类型招生控制线|特殊类型控制线)[^\d]{0,4}?(\d{2,3})"),
    # 形式：特招线历史类532 / 本科线物理类448（关键词在前）
    re.compile(r"(本科线|专科线|特招线|特殊类型招生控制线|特殊类型控制线)[^\d]{0,6}?"
               r"(历史类|物理类|文史类|理工类)[^\d]{0,4}?(\d{2,3})"),
    # 形式：本科批 历史类 463分
    re.compile(r"(本科批|提前本科批|高职（专科）批|高职\(专科\)批|专科批)[^\d]{0,6}?"
               r"(历史类|物理类|文史类|理工类)[^\d]{0,6}?(\d{3})"),
]


def parse_batch_lines_from_text(text: str, year: int) -> list[dict]:
    """从正文抽取「批次 × 科类 × 分数」。"""
    rows: list[dict] = []
    for pat in _BATCH_LINE_PATTERNS:
        for m in pat.finditer(text or ""):
            g = m.groups()
            if len(g) == 3 and g[0] in ("历史类", "物理类", "文史类", "理工类"):
                subj, batch_txt, score = g[0], g[1], g[2]
            else:
                batch_txt, subj, score = g[0], g[1], g[2]
            subj_n = config.normalize_subject(subj)
            batch = config.normalize_batch("特殊类型招生" if "特招" in batch_txt or "特殊类型" in batch_txt
                                           else batch_txt.replace("线", "") if batch_txt in ("本科线", "专科线")
                                           else batch_txt)
            if batch_txt == "本科线":
                batch = "本科批"
            elif batch_txt == "专科线":
                batch = "高职(专科)批"
            if subj_n:
                rows.append({"batch": batch, "subject_type": subj_n, "score": int(score)})
    # 去重
    uniq, seen = [], set()
    for r in rows:
        k = (r["batch"], r["subject_type"], r["score"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


def collect_batch_lines(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    records: list[Record] = []
    row_no = 0
    if not offline and fetcher:
        for url in config.URLS["batch_line"]:
            soup = fetcher.get_soup(url)
            if not soup:
                continue
            text = parsers.extract_article_text(soup)
            # 表格优先
            rows: list[dict] = []
            for table in soup.find_all("table"):
                for r in parsers.parse_html_table(table):
                    rows.extend(parse_batch_lines_from_text(" ".join(r), _year_from(text)))
            if not rows:
                rows = parse_batch_lines_from_text(text, _year_from(text))
            year = _year_from(text, 2025)
            for r in rows:
                row_no += 1
                records.append(_rec(
                    {"province": config.PROVINCE, "year": year, "batch": r["batch"],
                     "subject_type": r["subject_type"], "score": r["score"],
                     "track": "普通类"},
                    source_name=config.SOURCES["eol"]["name"], source_url=url,
                    year=year, doc_type="batch_score_line", row_no=row_no))
    if not records:  # 兜底：已核实基准值
        src = seeds.BENCHMARKS["benchmark_source"][0]
        for b in seeds.BENCHMARKS["batch_score_line"]:
            row_no += 1
            records.append(_rec(
                {"province": config.PROVINCE, "batch": b["batch"],
                 "subject_type": b["subject_type"], "score": b["score"], "track": "普通类"},
                source_name=src["name"], source_url=src["url"], year=b["year"],
                doc_type="batch_score_line", row_no=row_no))
    logger.info("A1 batch_score_line -> %d 条", len(records))
    return records


# ===========================================================================
# A2 · 一分一段统计表
#   来源：中国教育在线·掌上高考（转载江西省教育考试院）
#   解析：CSS 主表格 table tr -> [分数, 本段人数, 累计人数]；支持区间/批注单元格
# ===========================================================================
def collect_segments(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    records: list[Record] = []
    if offline or not fetcher:
        logger.warning("A2 一分一段需联网采集（离线模式跳过）")
        return records

    targets: list[tuple[int, str, str]] = [t for t in config.URLS["segment"] if t[2]]
    # 补发现：江西动态栏目中的「一分一段」文章
    try:
        list_soup = fetcher.get_soup("https://gaokao.eol.cn/jiang_xi/dongtai/",
                                     referer="https://gaokao.eol.cn/")
        if list_soup:
            for title, url in parsers.extract_links(
                    list_soup, "https://gaokao.eol.cn/jiang_xi/dongtai/", "一分一段"):
                y = _year_from(title or url, 2025)
                subj = ("三校生" if "三校生" in title else
                        "物理类" if "物理" in title else
                        "历史类" if "历史" in title else
                        "理工类" if "理工" in title else
                        "文史类" if "文史" in title else "")
                if subj:
                    targets.append((y, subj, url))
    except Exception as e:  # noqa: BLE001
        logger.warning("A2 栏目发现失败：%s", e)

    seen_url: set[str] = set()
    for year, subject, url in targets:
        if url in seen_url:
            continue
        seen_url.add(url)
        soup = fetcher.get_soup(url, referer="https://gaokao.eol.cn/")
        if not soup:
            continue
        grid = parsers.find_best_table(soup, min_rows=20, min_cols=3)
        if not grid:
            # 兜底1：页面内 PDF 链接（官方分段表常以 PDF 发布）
            for _, pdf_url in parsers.extract_links(soup, url):
                if not pdf_url.lower().endswith(".pdf"):
                    continue
                pdf = fetcher.get_bytes(pdf_url)
                if pdf:
                    for tb in parsers.parse_pdf_tables(pdf):
                        grid = (grid or []) + [list(r) for r in tb]
            # 兜底2：URL 本身即 PDF
            if not grid:
                pdf = fetcher.get_bytes(url)
                if pdf:
                    for tb in parsers.parse_pdf_tables(pdf):
                        grid = (grid or []) + [list(r) for r in tb]
        if not grid:
            logger.warning("A2 %s %s 未解析到表格：%s", year, subject, url)
            continue
        rows = parsers.fill_single_score_gaps(parsers.parse_segment_rows(grid))
        for i, r in enumerate(rows, start=1):
            records.append(_rec(
                {"province": config.PROVINCE, "year": year, "subject_type": subject,
                 "score": r["score"], "score_end": r["score_end"],
                 "same_score_count": r["same_score_count"],
                 "cumulative_rank": r["cumulative_rank"]},
                source_name="中国教育在线·掌上高考（转载江西省教育考试院）",
                source_url=url, year=year, doc_type="score_segment", row_no=i))
    logger.info("A2 score_segment -> %d 条", len(records))
    return records


# ===========================================================================
# A3 · 报名人数与录取统计
#   来源：江西省教育考试院工作动态 / 江西省教育厅通知公告
#   解析：正文正则抽取「报名总人数为64.63万」「实际参加6月统考56.71万」
# ===========================================================================
_STAT_PATTERNS = {
    "total_registered": r"报名(?:总)?人数为?\s*(\d+(?:\.\d+)?)\s*万",
    "actual_exam": r"实际参加(?:6月)?(?:统考|高考)(?:的)?(?:考生)?\s*(\d+(?:\.\d+)?)\s*万",
    "pre_admitted": r"(?:高职单招|单招)提前录取(?:的)?\s*(\d+(?:\.\d+)?)\s*万",
    "ordinary_count": r"普通类考生\s*(\d+(?:\.\d+)?)\s*万",
    "sanxiao_count": r"三校生类考生\s*(\d+(?:\.\d+)?)\s*万",
}


def parse_stat_from_text(text: str, year: int) -> dict:
    out: dict = {}
    for key, pat in _STAT_PATTERNS.items():
        m = re.search(pat, text or "")
        if m:
            out[key] = int(float(m.group(1)) * 10000)
    return out


def collect_stats(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    records: list[Record] = []
    row_no = 0
    if not offline and fetcher:
        for list_url in config.URLS["stat"]:
            soup = fetcher.get_soup(list_url)
            if not soup:
                continue
            for title, url in parsers.extract_links(soup, list_url, "高考"):
                if not re.search(r"高考|报名|考试", title or ""):
                    continue
                art = fetcher.get_soup(url)
                if not art:
                    continue
                text = parsers.extract_article_text(art)
                year = _year_from(title or text, 2025)
                data = parse_stat_from_text(text, year)
                if not data.get("total_registered"):
                    continue
                row_no += 1
                records.append(_rec(
                    {"province": config.PROVINCE, "year": year, "metric": "高考报名与考试",
                     **data},
                    source_name=config.SOURCES["jxeea"]["name"], source_url=url,
                    year=year, doc_type="province_stat", row_no=row_no))
    if not records:  # 兜底：已核实基准值
        src = seeds.BENCHMARKS["benchmark_source"][2]
        for s in seeds.BENCHMARKS["province_stat"]:
            row_no += 1
            records.append(_rec(
                {"province": config.PROVINCE, "metric": "高考报名与考试", **s},
                source_name=src["name"], source_url=src["url"], year=s["year"],
                doc_type="province_stat", row_no=row_no))
    logger.info("A3 province_stat -> %d 条", len(records))
    return records


# ===========================================================================
# A5 · 志愿填报与录取日程
#   来源：江西省教育考试院《录取工作通知》《志愿填报及投档规则》
#   解析：正文正则「第一次集中填报…6月26日9:00—27日17:00」
# ===========================================================================
# 兼容结束时间省略月份（如「6月30日9:00—7月4日17:00」与「6月26日9:00—27日17:00」）
_SCHEDULE_PAT = re.compile(
    r"(第[一二三]次集中填报)[^。；\n]{0,40}?"
    r"(\d{1,2}月\d{1,2}日\s*\d{1,2}[:：]\d{2})"
    r"\s*[—~\-－到至]+\s*"
    r"((?:\d{1,2}月)?\d{1,2}日\s*\d{1,2}[:：]\d{2})"
)


def parse_schedule_from_text(text: str, year: int) -> list[dict]:
    rows: list[dict] = []
    for m in _SCHEDULE_PAT.finditer(text or ""):
        rows.append({"stage": m.group(1).strip(), "start_time": m.group(2).strip(),
                     "end_time": m.group(3).strip(), "scope": ""})
    return rows


def collect_schedules(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    records: list[Record] = []
    row_no = 0
    if not offline and fetcher:
        for url in config.URLS["schedule"]:
            soup = fetcher.get_soup(url)
            if not soup:
                continue
            text = parsers.extract_article_text(soup)
            year = _year_from(parsers.extract_title(soup) or text, 2025)
            for r in parse_schedule_from_text(text, year):
                row_no += 1
                records.append(_rec(
                    {"province": config.PROVINCE, "year": year, **r},
                    source_name=config.SOURCES["jxeea"]["name"], source_url=url,
                    year=year, doc_type="schedule", row_no=row_no))
    if not records:
        src = seeds.BENCHMARKS["benchmark_source"][1]
        for s in seeds.BENCHMARKS["schedule"]:
            row_no += 1
            records.append(_rec(
                {"province": config.PROVINCE, **s},
                source_name=src["name"], source_url=src["url"], year=s["year"],
                doc_type="schedule", row_no=row_no))
    logger.info("A5 schedule -> %d 条", len(records))
    return records


# ===========================================================================
# A6 · 招生政策/录取规则全文（喂 RAG）
#   来源：省考试院公示公告 / 省教育厅通知公告
#   解析：CSS 列表页 a -> 详情页 div.content 正文
# ===========================================================================
_POLICY_KEYWORDS = ("志愿", "录取", "投档", "照顾", "加分", "体检", "军检", "报名办法", "招生工作")


def collect_policies(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    records: list[Record] = []
    if offline or not fetcher:
        return records
    row_no = 0
    for list_url in config.URLS["policy"]:
        soup = fetcher.get_soup(list_url)
        if not soup:
            continue
        for title, url in parsers.extract_links(soup, list_url):
            if not any(k in (title or "") for k in _POLICY_KEYWORDS):
                continue
            art = fetcher.get_soup(url)
            if not art:
                continue
            content = parsers.extract_article_text(art)
            if len(content) < 200:
                continue
            row_no += 1
            records.append(_rec(
                {"title": parsers.extract_title(art) or title,
                 "doc_category": "政策", "province": config.PROVINCE, "content": content},
                source_name=config.SOURCES["jxeea"]["name"], source_url=url,
                year=_year_from(title or content, 2025), doc_type="knowledge_doc", row_no=row_no))
    logger.info("A6 knowledge_doc(policy) -> %d 条", len(records))
    return records


# ===========================================================================
# A7 · 专项实施区域县名单（国家24 / 地方全省 / 高校58 / 苏区54）
#   来源：江西省教育厅专项通知（阳光高考转载）
#   解析：正文「xx市：县1、县2」逐县抽取；种子为已核验权威名单
# ===========================================================================
_PATHWAY_SECTION_PAT = re.compile(
    r"[（(]?[一二三四][）)]\s*(国家专项|地方专项|高校专项|苏区专项)[^。]{0,80}?"
    r"(?:实施区域为|实施区域|区域为)([^。]{0,900})"
)


def parse_counties_from_text(text: str) -> dict[str, list[tuple[str, str]]]:
    """返回 {专项: [(市, 县), ...]}。"""
    result: dict[str, list[tuple[str, str]]] = {}
    for m in _PATHWAY_SECTION_PAT.finditer(text or ""):
        pw = m.group(1) + "计划"
        body = m.group(2)
        counties: list[tuple[str, str]] = []
        for city_m in re.finditer(r"([\u4e00-\u9fa5]{2,6}市)[:：]\s*([^。；]{0,300})", body):
            city = city_m.group(1)
            for c in re.split(r"[、,，\s]+", city_m.group(2)):
                c = c.strip()
                if c and re.search(r"(县|区|市)$", c):
                    counties.append((city, c))
        if counties:
            result[pw] = counties
    return result


def collect_pathway_regions(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    """县名单以已核验种子为准；联网时尝试解析政策原文做增量/校验。"""
    records: list[Record] = []
    row_no = 0
    # 1) 种子（已核验，权威）
    for s in seeds.PATHWAY_REGION_SEEDS:
        row_no += 1
        records.append(_rec(
            {k: s[k] for k in ("pathway_name", "province", "city", "county_name",
                               "county_code", "scope")},
            source_name=s["source_name"], source_url=s["source_url"], year=s["year"],
            doc_type="pathway_region", row_no=row_no))
    # 2) 联网增量：解析政策原文，若出现种子中没有的县，补录并登记来源
    if not offline and fetcher:
        have = {(r.data["pathway_name"], r.data["county_name"]) for r in records}
        for url in config.URLS["pathway_region"][:1]:
            soup = fetcher.get_soup(url)
            if not soup:
                continue
            text = parsers.extract_article_text(soup)
            parsed = parse_counties_from_text(text)
            year = _year_from(text, 2024)
            for pw, counties in parsed.items():
                for city, county in counties:
                    if (pw, county) in have:
                        continue
                    have.add((pw, county))
                    row_no += 1
                    records.append(_rec(
                        {"pathway_name": pw, "province": config.PROVINCE, "city": city,
                         "county_name": county, "county_code": "", "scope": "实施区域"},
                        source_name=config.SOURCES["chsi"]["name"], source_url=url,
                        year=year, doc_type="pathway_region", row_no=row_no))
    cnt = seeds.region_counts()
    logger.info("A7 pathway_region -> %d 条（种子口径：%s）", len(records), cnt)
    return records


def collect_pathway_eligibility(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    """资格规则以已核验种子为准（四类专项条件各不相同）。"""
    records: list[Record] = []
    for i, s in enumerate(seeds.PATHWAY_ELIGIBILITY_SEEDS, start=1):
        records.append(_rec(
            {"pathway_name": s["pathway_name"], "province": s["province"],
             "rule_type": s["rule_type"], "rule_desc": s["rule_desc"], "params": s["params"]},
            source_name=s["source_name"], source_url=s["source_url"], year=s["year"],
            doc_type="pathway_eligibility", row_no=i))
    logger.info("A7 pathway_eligibility -> %d 条", len(records))
    return records


# ===========================================================================
# A8 · 途径字典（26 类）+ 特殊类型招生
# ===========================================================================
PATHWAYS_JX: list[dict] = [
    {"name": "强基计划", "category": "拔尖类", "batch": "提前本科批", "target_group": "基础学科拔尖", "priority": "P1"},
    {"name": "综合评价录取", "category": "拔尖类", "batch": "提前本科批", "target_group": "综合素质优秀", "priority": "P1"},
    {"name": "国家专项计划", "category": "专项类", "batch": "本科批", "target_group": "24个脱贫县考生", "priority": "P0"},
    {"name": "地方专项计划", "category": "专项类", "batch": "本科批", "target_group": "全省农村户籍考生", "priority": "P0"},
    {"name": "高校专项计划", "category": "专项类", "batch": "本科批", "target_group": "58个实施区域农村考生", "priority": "P0"},
    {"name": "苏区专项计划", "category": "专项类", "batch": "本科批", "target_group": "54个原中央苏区县考生", "priority": "P0"},
    {"name": "公费师范生", "category": "定向类", "batch": "提前本科批", "target_group": "有志从教考生", "priority": "P1"},
    {"name": "优师专项", "category": "定向类", "batch": "提前本科批", "target_group": "定向县从教考生", "priority": "P1"},
    {"name": "定向培养军士", "category": "军警类", "batch": "提前高职(专科)批", "target_group": "高职专科考生", "priority": "P1"},
    {"name": "农村订单定向医学生", "category": "定向类", "batch": "提前本科批", "target_group": "农村户籍考生", "priority": "P1"},
    {"name": "军队院校", "category": "军警类", "batch": "提前本科批", "target_group": "体检政审合格", "priority": "P1"},
    {"name": "公安司法消防院校", "category": "军警类", "batch": "提前本科批", "target_group": "体检政审合格", "priority": "P1"},
    {"name": "民航招飞（飞行员）", "category": "军警类", "batch": "提前本科批", "target_group": "体检合格", "priority": "P1"},
    {"name": "艺术类", "category": "艺体类", "batch": "提前本科批/本科批", "target_group": "艺术生", "priority": "P1"},
    {"name": "体育类", "category": "艺体类", "batch": "提前本科批/本科批", "target_group": "体育生", "priority": "P1"},
    {"name": "高水平运动队", "category": "艺体类", "batch": "本科批特殊选拔", "target_group": "体育特长", "priority": "P2"},
    {"name": "高水平艺术团", "category": "艺体类", "batch": "本科批特殊选拔", "target_group": "艺术特长", "priority": "P2"},
    {"name": "保送生", "category": "拔尖类", "batch": "提前本科批", "target_group": "竞赛/外国语学校", "priority": "P2"},
    {"name": "高职单招", "category": "其他", "batch": "高职单招", "target_group": "中职/高中毕业生", "priority": "P2"},
    {"name": "三校生类招生", "category": "其他", "batch": "三校生类", "target_group": "三校生", "priority": "P1"},
    {"name": "港澳高校自主招生", "category": "其他", "batch": "单独录取", "target_group": "全体考生", "priority": "P2"},
    {"name": "中外合作办学", "category": "其他", "batch": "本科批", "target_group": "全体考生", "priority": "P2"},
    {"name": "民族班/预科班", "category": "其他", "batch": "本科批", "target_group": "少数民族等", "priority": "P2"},
    {"name": "航海类专业", "category": "其他", "batch": "提前本科批", "target_group": "航海类", "priority": "P2"},
    {"name": "小语种专业", "category": "其他", "batch": "提前本科批", "target_group": "小语种", "priority": "P2"},
    {"name": "马克思主义理论专业", "category": "其他", "batch": "提前本科批", "target_group": "相关考生", "priority": "P2"},
]


def collect_pathways(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    records: list[Record] = []
    for i, p in enumerate(PATHWAYS_JX, start=1):
        records.append(_rec(
            {"name": p["name"], "category": p["category"], "batch": p["batch"],
             "target_group": p["target_group"], "priority": p["priority"],
             "data_status": "available" if p["priority"] == "P0" else "schema_only"},
            source_name="教育部阳光高考平台 + 江西省教育考试院政策文件",
            source_url="https://gaokao.chsi.com.cn/", year=2025,
            doc_type="pathway", row_no=i))
    logger.info("A8 pathway -> %d 类", len(records))
    return records


def collect_special_types(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    """特殊类型招生简章（强基/综评/军警/招飞），落 knowledge_doc。"""
    records: list[Record] = []
    if offline or not fetcher:
        return records
    row_no = 0
    for list_url in config.URLS["special_type"]:
        soup = fetcher.get_soup(list_url)
        if not soup:
            continue
        for title, url in parsers.extract_links(soup, list_url):
            if not re.search(r"强基|综合评价|招飞|军|警|公费师范|优师", title or ""):
                continue
            art = fetcher.get_soup(url)
            if not art:
                continue
            content = parsers.extract_article_text(art)
            if len(content) < 200:
                continue
            row_no += 1
            records.append(_rec(
                {"title": parsers.extract_title(art) or title, "doc_category": "特殊类型招生",
                 "province": "全国", "content": content},
                source_name=config.SOURCES["chsi"]["name"], source_url=url,
                year=_year_from(title or content, 2025), doc_type="knowledge_doc", row_no=row_no))
    logger.info("A8 knowledge_doc(special) -> %d 条", len(records))
    return records


# ===========================================================================
# B1 · 院校库（掌上高考 API，province_id=36=江西）
#   来源：中国教育在线·掌上高考 API（api.eol.cn/gkcx）
#   解析：JSON 结构化（字段映射见 c_school.py 同源）
# ===========================================================================
EOL_API = "https://api.eol.cn/gkcx/api/"
JX_PROVINCE_ID = "36"  # 江西省行政区划码


def collect_schools(fetcher: Fetcher | None, *, offline: bool = False,
                    limit: int | None = None) -> list[Record]:
    records: list[Record] = []
    if offline:
        logger.warning("B1 院校库需联网采集（离线模式跳过）")
        return records
    if not fetcher:
        return records
    page, total = 1, None
    while page <= 20:
        try:
            r = fetcher.get(EOL_API, params={
                "access_token": "", "uri": "apidata/api/gk/school/lists",
                "signsafe": "", "province_id": JX_PROVINCE_ID,
                "page": str(page), "size": "100"})
            if r is None:
                break
            data = r.json().get("data", {})
        except Exception as e:  # noqa: BLE001
            logger.error("B1 院校库第 %d 页失败：%s", page, e)
            break
        items = data.get("item", [])
        if total is None:
            total = int(data.get("numFound", 0) or 0)
            logger.info("B1 江西院校总数：%s", total)
        if not items:
            break
        for it in items:
            digits = "".join(ch for ch in (it.get("code_enroll") or "") if ch.isdigit())
            records.append(_rec(
                {"name": it.get("name", ""), "code": digits[:5],
                 "province_code": "", "province": it.get("province_name", "江西"),
                 "city": it.get("city_name", ""), "level": it.get("level_name", ""),
                 "type": it.get("type_name", ""), "ownership": it.get("nature_name", ""),
                 "website": "", "intro": "",
                 "is_211": it.get("f211") == "1", "is_985": it.get("f985") == "1",
                 "dual_class": it.get("dual_class_name", ""),
                 "external_id": it.get("school_id")},
                source_name=config.SOURCES["eol"]["name"],
                source_url=f"https://www.gaokao.cn/school/{it.get('school_id')}",
                year=2026, doc_type="school", row_no=len(records) + 1))
        if total and len(records) >= total:
            break
        if limit and len(records) >= limit:
            break
        page += 1
    logger.info("B1 school -> %d 所", len(records))
    return records


# ===========================================================================
# B3 · 各批次投档线/录取分（院校专业组）
#   来源：江西省教育考试院「各批次投档情况」公告
#   解析（双通道，均取官方原文）：
#     ① 正文分组行：`1.代码1006，清华大学，第103组，669分`
#        → 每年每科类「投档分居前」的院校专业组（含国家专项等标注）
#     ② 文章附件 PDF（完整统计表）：列 =
#        序号|科类|院校代码|院校名称|专业组代号|专业组名称|投档线|最低投档排名|备注
#        → pdfplumber 抽表，覆盖全部院校专业组（含投档位次）
# ===========================================================================
_GROUP_PAT = re.compile(r"第\s*(\d+)\s*组")

# 正文分组行： 1.代码1006，清华大学，第103组（国家专项），669分
_BODY_GROUP_PAT = re.compile(
    r"\d+\s*[.．、]\s*代码\s*(\d{3,4})\s*[，,]\s*([^，,、]+?)\s*[，,]\s*"
    r"(第[^，,、]+?组(?:[（(][^）)]*[）)])?)\s*[，,]\s*(\d{2,3}(?:\.\d+)?)\s*分"
)


def _batch_from_title(t: str) -> str:
    if "提前" in t:
        return "提前本科批"
    if "高职" in t or "专科" in t:
        return "高职(专科)批"
    return "本科批"


def _find_pdf_links(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """抽取文章内的附件链接（PDF/Word/Excel）→ [(文件名, 绝对URL)]。"""
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if re.search(r"\.(pdf|docx?|xlsx?)(\?|$)", href, re.I):
            out.append((a.get_text(" ", strip=True), urljoin(base_url, href)))
    return out


def collect_admissions(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    records: list[Record] = []
    if offline or not fetcher:
        logger.warning("B3 投档线需联网采集（离线模式跳过）")
        return records

    # 1) 组装目标文章 URL：固定入口（原文/统计表）+ 栏目页检索「投档」
    targets: list[str] = []
    list_pages: list[str] = []
    for u in config.URLS["admission"]:
        if u.endswith("list.html"):
            list_pages.append(u)
        else:
            targets.append(u)
    for list_url in list_pages:
        soup = fetcher.get_soup(list_url)
        if not soup:
            continue
        for title, url in parsers.extract_links(soup, list_url, "投档"):
            if url not in targets:
                targets.append(url)

    row_no = 0
    seen_art: set[str] = set()
    for url in targets:
        if url in seen_art:
            continue
        seen_art.add(url)
        art = fetcher.get_soup(url)
        if not art:
            continue
        title = parsers.extract_title(art) or ""
        text = parsers.extract_article_text(art)
        year = _year_from(title or text, 2025)
        batch = _batch_from_title(title or text)

        # ① 正文分组行（投档分居前的院校专业组；按科类段落跟踪 subject_type）
        #    仅保留普通类（历史/物理）与三校生；艺术/体育为综合分，跳过。
        cur_subject: str | None = None
        for line in re.split(r"[\n。；]", text):
            if re.search(r"(艺术|体育)", line) and re.search(r"(投档|录取)", line):
                cur_subject = None
            elif "三校生" in line and re.search(r"(投档|录取)", line):
                cur_subject = "三校生"
            elif len(line) <= 30 and re.search(r"(科目组|科类)", line):
                cur_subject = config.normalize_subject(line)
            if cur_subject is None:
                continue
            for m in _BODY_GROUP_PAT.finditer(line):
                code, name, group, score = m.groups()
                gm = _GROUP_PAT.search(group or "")
                row_no += 1
                records.append(_rec(
                    {"school_name": name.strip(), "school_code": code.strip(),
                     "province": config.PROVINCE, "batch": batch,
                     "subject_type": cur_subject,
                     "group_code": gm.group(1) if gm else None,
                     "group_name": (group or "").strip() or None,
                     "min_score": parsers.to_int(score), "min_rank": None, "plan_count": None},
                    source_name=config.SOURCES["jxeea"]["name"], source_url=url,
                    year=year, doc_type="school_major_score", row_no=row_no))

        # ② PDF 附件（完整统计表）
        for fname, pdf_url in _find_pdf_links(art, url):
            pdf = fetcher.get_bytes(pdf_url)
            if not pdf:
                continue
            for tb in parsers.parse_pdf_tables(pdf):
                for r in tb:
                    if len(r) < 7:
                        continue
                    cells = [(c or "").strip() for c in r]
                    subject = config.normalize_subject(cells[1])
                    code, name = cells[2], cells[3]
                    if not subject or not re.search(r"\d{3,4}", code) or not name:
                        continue
                    score = parsers.to_int(cells[6])
                    if score is None:
                        continue
                    row_no += 1
                    records.append(_rec(
                        {"school_name": name, "school_code": code,
                         "province": config.PROVINCE, "batch": batch,
                         "subject_type": subject,
                         "group_code": cells[4] or None,
                         "group_name": cells[5] or None,
                         "min_score": score,
                         "min_rank": parsers.to_int(cells[7]) if len(cells) > 7 else None,
                         "plan_count": None},
                        source_name=config.SOURCES["jxeea"]["name"], source_url=pdf_url,
                        year=year, doc_type="school_major_score", row_no=row_no))
    logger.info("B3 school_major_score -> %d 条", len(records))
    return records


# ===========================================================================
# B5 · 招生章程
#   来源：教育部阳光高考平台·招生章程栏目
#   解析：CSS 列表 a.sch-item -> 章程详情 div.content
# ===========================================================================
def collect_charters(fetcher: Fetcher | None, *, offline: bool = False,
                     limit: int | None = None) -> list[Record]:
    records: list[Record] = []
    if offline or not fetcher:
        return records
    row_no = 0
    for list_url in config.URLS["charter"]:
        soup = fetcher.get_soup(list_url)
        if not soup:
            continue
        for title, url in parsers.extract_links(soup, list_url):
            if "章程" not in (title or ""):
                continue
            art = fetcher.get_soup(url)
            if not art:
                continue
            content = parsers.extract_article_text(art)
            if len(content) < 200:
                continue
            school = re.sub(r"\d{4}年.*$", "", title).strip() or title
            row_no += 1
            records.append(_rec(
                {"school_name": school, "year": _year_from(title, 2025),
                 "content": content, "subject_req": None, "health_req": None,
                 "foreign_lang_req": None},
                source_name=config.SOURCES["chsi"]["name"], source_url=url,
                year=_year_from(title, 2025), doc_type="enrollment_rule", row_no=row_no))
            if limit and row_no >= limit:
                return records
    logger.info("B5 enrollment_rule -> %d 条", len(records))
    return records


# ===========================================================================
# B3 补充 / B4 / B6 · 院校专业组投档线·最低分·最低位次·选科要求
#   来源：掌上高考数据接口 apidata/api/gk/score/province（招生省 = 江西）
#   目标 URL：https://api.eol.cn/gkcx/api/（?uri=…&local_province_id=36&year=…）
#   解析方式：JSON → data.item[]；一条 = 某校某专业组在某科类/批次的
#             filing(投档线) / min(最低分) / min_section(最低位次) /
#             num(计划数) / proscore(省控线) / sg_info(选科要求)
#   同时派生 doc_type=subject_requirement（B4 选科要求）。
# ===========================================================================
_EOL_SCORE_URI = "apidata/api/gk/score/province"
_EOL_YEARS = [2023, 2024, 2025]
# 首选/再选科目代码 → 名称（eol 内部码）
_SG_FXK_NAME = {"70000": "物理", "70001": "历史"}
_SG_SXK_NAME = {"70001": "化学", "70002": "生物", "70003": "思想政治",
                "70004": "地理", "70005": "历史"}


def _flag(v) -> bool:
    """接口布尔标记：1 / "1" / True → 真。"""
    return str(v).strip() in ("1", "True", "true")


def _to_int(v, *, positive: bool = False) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ("-", "—", "－"):
        return None
    try:
        n = int(float(s))
    except Exception:  # noqa: BLE001
        m = re.search(r"\d+", s)
        if not m:
            return None
        n = int(m.group())
    if positive and n <= 0:
        return None
    return n


def _eol_api(fetcher: Fetcher, uri: str, **params):
    """调用掌上高考数据接口，返回 data 字段（失败 None）。"""
    q = {"access_token": "", "uri": uri, "signsafe": ""}
    q.update({k: str(v) for k, v in params.items()})
    r = fetcher.get(EOL_API, params=q, headers={"Referer": "https://www.gaokao.cn/"})
    if r is None:
        return None
    try:
        return r.json().get("data")
    except Exception:  # noqa: BLE001
        return None


def collect_group_admissions(fetcher: Fetcher | None, *, offline: bool = False,
                             limit: int | None = None) -> list[Record]:
    """B6 院校专业组投档/录取分（含最低位次）+ 派生 B4 选科要求。"""
    records: list[Record] = []
    if offline or not fetcher:
        logger.warning("B6 专业组录取数据需联网（离线模式跳过）")
        return records
    row_no = 0
    for year in _EOL_YEARS:
        page = 1
        while page <= 500:
            data = _eol_api(fetcher, _EOL_SCORE_URI, local_province_id=JX_PROVINCE_ID,
                            year=year, page=page, size=20)
            if not isinstance(data, dict):
                logger.warning("B6 %s 第 %d 页空/限流，停止该年", year, page)
                break
            items = data.get("item") or []
            if not items:
                break
            for it in items:
                subj = config.normalize_subject(it.get("local_type_name"))
                if not subj:
                    continue
                row_no += 1
                sid = it.get("school_id")
                src = f"https://www.gaokao.cn/school/{sid}/provinceline"
                records.append(_rec(
                    {"school_name": it.get("name", ""), "school_id": sid,
                     "group_name": it.get("sg_name", ""),
                     "group_code": re.sub(r"[（）()]", "", it.get("sg_name") or ""),
                     "year": year, "batch": config.normalize_batch(it.get("local_batch_name")),
                     "subject_type": subj,
                     "min_score": _to_int(it.get("min"), positive=True),
                     "filing_score": _to_int(it.get("filing"), positive=True),
                     "min_rank": _to_int(it.get("min_section"), positive=True),
                     "score_line": _to_int(it.get("proscore"), positive=True),
                     "plan_count": _to_int(it.get("num")),
                     "avg_score": _to_int(it.get("average"), positive=True),
                     "max_score": _to_int(it.get("max"), positive=True),
                     "admission_type": it.get("zslx_name", ""),
                     "school_province": it.get("province_name", ""),
                     "school_city": it.get("city_name", ""),
                     "school_level": it.get("level_name", ""),
                     "school_nature": it.get("nature_name", ""),
                     "school_type": it.get("type_name", ""),
                     "dual_class": it.get("dual_class_name", ""),
                     "is_985": _flag(it.get("f985")), "is_211": _flag(it.get("f211")),
                     "subject_req": it.get("sg_info", "")},
                    source_name=config.SOURCES["eol"]["name"], source_url=src,
                    year=year, doc_type="group_admission", row_no=row_no))
                # 派生 B4 选科要求
                if it.get("sg_info"):
                    records.append(_rec(
                        {"school_name": it.get("name", ""), "group_name": it.get("sg_name", ""),
                         "subject_req": it.get("sg_info", ""),
                         "first_require": _SG_FXK_NAME.get(str(it.get("sg_fxk")), ""),
                         "second_require": it.get("sg_sxk", ""),
                         "subject_type": subj, "year": year},
                        source_name=config.SOURCES["eol"]["name"], source_url=src,
                        year=year, doc_type="subject_requirement", row_no=row_no))
            page += 1
            if limit and len(records) >= limit:
                break
        logger.info("B6 %s 采集累计 %d 条", year, len(records))
        if limit and len(records) >= limit:
            break
    logger.info("B6 group_admission + B4 subject_requirement -> %d 条", len(records))
    return records


# ===========================================================================
# B2 · 在赣招生计划（分专业组/专业）· B7 · 征集志愿（缺额）
#   来源：江西省教育考试院「通知公告」栏目（征集志愿填报说明 + .xls 附件）
#   目标 URL：https://www.jxeea.cn/jxsjyksy/tzgg92/content/content_*.html
#   解析：正文 div#zoom 抽征集时间；附件 .xls（OLE2）→ xlrd 抽
#         缺额院校专业组及专业统计表（列：序号|科类|院校代号|院校名称|
#         专业组代号|专业组名称|专业组缺额|专业代号|专业名称|选考科目要求|备注）
# ===========================================================================
def _read_spreadsheet(content: bytes) -> list[tuple[str, list[list]]]:
    """读 .xls/.xlsx 为 [(sheet_name, rows)]；失败返回 []。"""
    out: list[tuple[str, list[list]]] = []
    try:
        import xlrd
        book = xlrd.open_workbook(file_contents=content)
        for sh in book.sheets():
            rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
            out.append((sh.name, rows))
        return out
    except Exception:  # noqa: BLE001
        pass
    try:
        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows = [[c for c in row] for row in ws.iter_rows(values_only=True)]
            out.append((ws.title, rows))
    except Exception as e:  # noqa: BLE001
        logger.warning("表格解析失败：%s", e)
    return out


def _header_index(rows: list[list], keywords: list[str]) -> int:
    """定位包含全部关键词的表头行。"""
    for i, row in enumerate(rows[:8]):
        cells = [str(c).replace("\n", "").strip() for c in row]
        joined = "".join(cells)
        if all(k in joined for k in keywords):
            return i
    return -1


def _col(header: list[str], *kw: str) -> int:
    for i, h in enumerate(header):
        if all(k in h for k in kw):
            return i
    return -1


_SUP_BATCH_PAT = re.compile(r"(提前本科|本科|提前高职[(（]专科[)）]|高职[(（]专科[)）]|专科)")


def collect_supplements(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    """B7 征集志愿（缺额院校专业组及专业）+ B2 专业级计划。"""
    records: list[Record] = []
    if offline or not fetcher:
        logger.warning("B7 征集志愿需联网（离线模式跳过）")
        return records
    row_no = 0
    for url in config.URLS["supplement"]:
        soup = fetcher.get_soup(url)
        if not soup:
            continue
        title = ""
        if soup.title:
            title = soup.title.get_text(strip=True)
        year = _year_from(title, 2026)
        bm = _SUP_BATCH_PAT.search(title)
        raw_b = bm.group(1) if bm else "本科"
        raw_b = raw_b.replace("(", "（").replace(")", "）")
        if raw_b == "本科":
            raw_b = "本科批"
        elif raw_b in ("高职（专科）", "专科"):
            raw_b = "高职(专科)批"
        batch = config.normalize_batch(raw_b)
        round_m = re.search(r"第([一二三四])次", title)
        round_name = f"第{round_m.group(1)}次" if round_m else ("提前" if "提前" in title else "")
        zoom = soup.select_one("#zoom") or soup.body
        text = zoom.get_text("", strip=True) if zoom else ""
        text_flat = re.sub(r"\s+", "", text)
        tm = re.search(r"填报\s*时间为[:：]?\s*([0-9]{1,2}月[0-9]{1,2}日[^。；]{0,18}?时)", text_flat)
        collect_time = tm.group(1) if tm else ""
        # 附件 .xls（缺额院校专业组及专业统计表）
        atts: list[tuple[str, str]] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if re.search(r"\.(xls|xlsx)$", href, re.I):
                atts.append((a.get_text(" ", strip=True), urljoin(url, href)))
        for att_title, att_url in atts:
            if "缺额" not in att_title:
                continue
            content = fetcher.get_bytes(att_url)
            if not content:
                continue
            for sheet_name, rows in _read_spreadsheet(content):
                hi = _header_index(rows, ["院校名称", "专业组", "缺额"])
                if hi < 0:
                    continue
                header = [str(c).replace("\n", "").strip() for c in rows[hi]]
                ci = {
                    "subject": _col(header, "科类"),
                    "school_code": _col(header, "院校代号"),
                    "school_name": _col(header, "院校名称"),
                    "group_code": _col(header, "专业组代号"),
                    "group_name": _col(header, "专业组名称"),
                    "plan": _col(header, "缺额"),
                    "major_code": _col(header, "专业代号"),
                    "major_name": _col(header, "专业名称"),
                    "subject_req": _col(header, "科目"),
                }
                for r in rows[hi + 1:]:
                    def g(key: str) -> str:
                        idx = ci.get(key, -1)
                        if idx < 0 or idx >= len(r) or r[idx] is None:
                            return ""
                        v = r[idx]
                        if isinstance(v, float) and v == int(v):
                            return str(int(v))
                        return str(v).strip()
                    sname = g("school_name")
                    if not sname:
                        continue
                    raw_subj = g("subject")
                    subj = config.normalize_subject(raw_subj) or raw_subj or "综合"
                    plan = _to_int(g("plan"))
                    gname = g("group_name")
                    gc = g("group_code") or re.sub(r"[^\d]", "", gname)
                    row_no += 1
                    common = {
                        "year": year, "batch": batch, "round": round_name,
                        "subject_type": subj, "school_name": sname,
                        "school_code": g("school_code"), "group_code": gc,
                        "group_name": gname, "major_code": g("major_code"),
                        "major_name": g("major_name"), "plan_count": plan,
                        "subject_req": g("subject_req"), "collect_time": collect_time,
                    }
                    records.append(_rec(
                        dict(common, doc_type="supplement"),
                        source_name=config.SOURCES["jxeea"]["name"], source_url=att_url,
                        year=year, doc_type="supplement", row_no=row_no))
                    # 派生 B2 专业级计划
                    records.append(_rec(
                        {"school_name": sname, "school_code": g("school_code"),
                         "group_code": gc, "group_name": gname,
                         "major_code": g("major_code"), "major_name": g("major_name"),
                         "plan_count": plan, "batch": batch, "subject_type": subj,
                         "round": round_name, "year": year,
                         "degree": f"{batch}（{round_name}缺额）" if round_name else batch},
                        source_name=config.SOURCES["jxeea"]["name"], source_url=att_url,
                        year=year, doc_type="school_plan", row_no=row_no))
        logger.info("B7 %s -> 累计 %d 条", title[:30], len(records))
    logger.info("B7 supplement + B2 school_plan -> %d 条", len(records))
    return records


def collect_school_plans(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    """B2 在赣招生计划（分专业）——由 B7 征集公告附件派生（见 collect_supplements）。"""
    return []


def collect_subject_reqs(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    """B4 选科要求——由掌上高考录取数据派生（见 collect_group_admissions）。"""
    return []


def collect_major_scores(fetcher: Fetcher | None, *, offline: bool = False) -> list[Record]:
    """B6 分专业录取分——由专业组投档数据覆盖（见 collect_group_admissions）。"""
    return []


# ===========================================================================
# B8 · 院校画像（层次/类型/办学性质/双一流·985·211/所在省市）
#   来源：掌上高考院校库接口 apidata/api/gk/school/lists（全国院校，分页）
#   目标 URL：https://api.eol.cn/gkcx/api/
#   解析方式：JSON → data.item[]
# ===========================================================================
def collect_profiles(fetcher: Fetcher | None, *, offline: bool = False,
                     limit: int | None = None) -> list[Record]:
    records: list[Record] = []
    if offline or not fetcher:
        logger.warning("B8 院校画像需联网（离线模式跳过）")
        return records
    page = 1
    row_no = 0
    while page <= 200:
        data = _eol_api(fetcher, "apidata/api/gk/school/lists", page=page, size=20)
        if not isinstance(data, dict):
            logger.warning("B8 第 %d 页空/限流，停止", page)
            break
        items = data.get("item") or []
        if not items:
            break
        for it in items:
            row_no += 1
            sid = it.get("school_id")
            digits = "".join(ch for ch in (it.get("code_enroll") or "") if ch.isdigit())
            records.append(_rec(
                {"school_name": it.get("name", ""), "school_code": digits[:5],
                 "school_id": sid, "province": it.get("province_name", ""),
                 "city": it.get("city_name", ""), "level": it.get("level_name", ""),
                 "type": it.get("type_name", ""), "ownership": it.get("nature_name", ""),
                 "dual_class": it.get("dual_class_name", ""),
                 "is_985": _flag(it.get("f985")), "is_211": _flag(it.get("f211")),
                 "belong": it.get("belong", ""),
                 "website": f"https://www.gaokao.cn/school/{sid}",
                 "intro": ""},
                source_name=config.SOURCES["eol"]["name"],
                source_url=f"https://www.gaokao.cn/school/{sid}",
                year=2026, doc_type="school_profile", row_no=row_no))
        if limit and len(records) >= limit:
            break
        total = int(data.get("numFound", 0) or 0)
        if total and len(records) >= total:
            break
        page += 1
    logger.info("B8 school_profile -> %d 所", len(records))
    return records


# ===========================================================================
# 汇总：模块 → 采集器（供 run.py 编排）
# ===========================================================================
COLLECTORS = {
    "batch": collect_batch_lines,
    "segment": collect_segments,
    "stat": collect_stats,
    "schedule": collect_schedules,
    "policy": collect_policies,
    "region": collect_pathway_regions,
    "eligibility": collect_pathway_eligibility,
    "pathway": collect_pathways,
    "special": collect_special_types,
    "school": collect_schools,
    "admission": collect_admissions,
    "charter": collect_charters,
    "group_admission": collect_group_admissions,
    "supplement": collect_supplements,
    "profile": collect_profiles,
    # 以下为派生/占位（其数据由上面的 group_admission / supplement 一并产出）
    "plan": collect_school_plans,
    "subject_req": collect_subject_reqs,
    "major_score": collect_major_scores,
}

DEFAULT_ORDER = ["region", "eligibility", "pathway", "batch", "stat", "schedule",
                 "segment", "school", "admission", "group_admission",
                 "charter", "policy", "special", "plan", "subject_req",
                 "major_score", "supplement", "profile"]

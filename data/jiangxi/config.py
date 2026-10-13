"""
江西高考数据采集 · 配置中心。

本文件是「字段 → 来源 → 目标 URL → 解析方式」的唯一权威映射（对应爬取清单
`爬取数据清单_江西_张.md` 的模块 A1–A8 / B1–B8）。
- SOURCES      ：数据源白名单（合规必需，只采这些）
- URLS         ：各模块的目标 URL 注册表（逐年/逐科类）
- FIELD_MAP    ：逐模块、逐字段的来源与解析方式（`--fieldmap` 可打印）
- 枚举归一     ：科类/批次口径统一（江西新老高考跨年）
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# 基础常量
# ---------------------------------------------------------------------------
PROVINCE = "江西"
YEARS = [2023, 2024, 2025]

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR.parent / "raw_jx"          # 原始响应落盘（走网盘，不入库）
OUTPUT_DIR = BASE_DIR / "output"              # 清洗结果 JSON + CSV
SEED_DIR = BASE_DIR / "seeds"                 # 种子数据目录

# ---------------------------------------------------------------------------
# 请求头（完整浏览器头，降低被判定为脚本的概率）
# ---------------------------------------------------------------------------
HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

# 反爬参数（对齐项目 data/collectors/base.py 的口径）
SLEEP_SECONDS = 2.0        # 单站请求最小间隔（秒），另加 0~0.5s 随机抖动
RETRY_TIMES = 3            # 失败重试次数
TIMEOUT = 25.0             # 单次请求超时（秒）
BACKOFF_BASE = 1.5         # 指数退避基数
MAX_PAGES_PER_SECTION = 60  # 单栏目最多翻页数（防止无限翻页）

# ---------------------------------------------------------------------------
# 一、数据源白名单（只从这些公开渠道采；每条数据登记来源三要素）
# ---------------------------------------------------------------------------
SOURCES: dict[str, dict] = {
    "jxeea": {
        "name": "江西省教育考试院",
        "base": "https://www.jxeea.cn",
        "source_type": "官方",
        "reliability": "high",
    },
    "jxedu": {
        "name": "江西省教育厅",
        "base": "https://jyt.jiangxi.gov.cn",
        "source_type": "官方",
        "reliability": "high",
    },
    "chsi": {
        "name": "教育部阳光高考平台",
        "base": "https://gaokao.chsi.com.cn",
        "source_type": "官方",
        "reliability": "high",
    },
    "eol": {
        "name": "中国教育在线·掌上高考",
        "base": "https://gaokao.eol.cn",
        "source_type": "公开网络",
        "reliability": "medium",
    },
}

# 明确不采：需登录的 jxgk.jxeea.cn 成绩/志愿系统、任何个人隐私数据

# ---------------------------------------------------------------------------
# 二、目标 URL 注册表
#    说明：江西政府站为 http/https 混合，沙箱下 http(:80) 常返回 403，
#          统一改走 https；部分栏目为列表页需二次进入详情页。
# ---------------------------------------------------------------------------
URLS: dict[str, object] = {
    # ---- A1 批次控制线（省考试院公示公告 + 掌上高考江西栏目）----
    "batch_line": [
        # 掌上高考·江西分数线栏目（含官方口径转载，HTML 表格/正文）
        "https://gaokao.eol.cn/jiang_xi/dongtai/",
        # 省考试院公示公告（录取控制分数线原文）
        "https://www.jxeea.cn/jxsjyksy/gsgg91/list.html",
        # 省考试院·普通高考栏目（分数线/投档/征集最集中）
        "https://www.jxeea.cn/jxsjyksy/ptgk49/list.html",
    ],

    # ---- A2 一分一段表（科类 → 逐年 URL；已知 2024 两条，其余按栏目检索）----
    "segment": [
        # 2024 物理类（实测可解析，HTML 表格；数值与官方一致：681及以上 34/34）
        (2024, "物理类", "https://gaokao.eol.cn/jiang_xi/dongtai/202406/t20240626_2619478.shtml"),
        # 2024 历史类（同栏目，实测可解析）
        (2024, "历史类", "https://gaokao.eol.cn/jiang_xi/dongtai/202406/t20240626_2619467.shtml"),
        # 2024 三校生（官方仅提供 PDF；见下方 segment_pdf）
        (2024, "三校生", ""),
        # 其余年份/科类走「江西动态」栏目检索（见 collect_segments 内的链接发现）
        (2023, "理工类", ""),
        (2023, "文史类", ""),
        (2025, "物理类", ""),
        (2025, "历史类", ""),
    ],

    # A2 补充：省考试院官方 PDF（三校生/历史类等，需 pdfplumber）
    "segment_pdf": [
        # 江西省2024年普通高考历史类一分一段表（省考试院）
        "http://www.jxeea.cn/jxsjyksy/gsgg91/1856091555406221312/2JEulIxD.pdf",
        # 2024 分段表汇总页（含 历史/物理/三校生 三张 PDF 链接）
        "https://gaokao.eol.cn/jiang_xi/dongtai/202406/t20240626_2619469.shtml",
    ],

    # ---- A3 报名人数与录取统计（省考试院新闻 / 教育厅发布）----
    "stat": [
        "https://www.jxeea.cn/jxsjyksy/gzdt38/pc/list.html",     # 工作动态（高考新闻发布会）
        "https://jyt.jiangxi.gov.cn/jxjyw/tzgg785/",  # 通知公告
    ],

    # ---- A4 招生计划总量（省考试院）----
    "plan_summary": [
        "https://www.jxeea.cn/jxsjyksy/gsgg91/list.html",
    ],

    # ---- A5 志愿填报与录取日程（录取工作通知 + 志愿填报问答）----
    "schedule": [
        "https://www.jxeea.cn/jxsjyksy/gsgg91/content/content_1938140931900411904.html",
        "https://www.jxeea.cn/jxsjyksy/cjwd80/content/content_1937322656332894208.html",
    ],

    # ---- A6 招生政策/录取规则全文（喂 RAG）----
    "policy": [
        "https://www.jxeea.cn/jxsjyksy/gsgg91/list.html",
        "https://jyt.jiangxi.gov.cn/jxjyw/tzgg785/",
    ],

    # ---- A7 专项计划（四类：国家/地方/高校/苏区）----
    "pathway_region": [
        # 阳光高考转载江西省教育厅《专项计划招生工作的通知》（含四类实施区域）
        "https://gaokao.chsi.com.cn/gkxx/zc/ss/202312/20231201/2293172455.html",
        # 省教育厅年度专项通知（逐年）
        "https://jyt.jiangxi.gov.cn/jxjyw/tzgg785/",
    ],

    # ---- A8 特殊类型招生（强基/综评/军警/招飞/公费师范）----
    "special_type": [
        "https://gaokao.chsi.com.cn/gkxx/zszcgd/",     # 阳光高考·招生政策规定
        "https://gaokao.chsi.com.cn/gkzt/gxzxfx/",     # 阳光高考·高校专项
    ],

    # ---- B1 院校库（阳光高考院校库，结构规范）----
    "school": [
        "https://gaokao.chsi.com.cn/sch/search.do",
    ],

    # ---- B2 在赣招生计划 / B3 投档线 / B4 选科要求（省考试院投档公告 + 阳光高考）----
    "admission": [
        # 固定入口①：投档情况统计表（文章内含 PDF 附件＝完整投档线＋位次）
        "https://www.jxeea.cn/jxsjyksy/gsgg91/content/content_1856090614535753728.html",
        # 固定入口②：本科批投档情况发布（正文含各科类「投档分居前」的院校专业组）
        "https://www.jxeea.cn/jxsjyksy/gzdt38/pc/content/content_1856075405393858560.html",
        # 栏目检索：普通高考 / 公示公告（逐年「投档」公告）
        "https://www.jxeea.cn/jxsjyksy/ptgk49/list.html",
        "https://www.jxeea.cn/jxsjyksy/gsgg91/list.html",
        "https://gaokao.chsi.com.cn/zsjh/searchZsjh--method-index.dhtml",  # 阳光高考招生计划
    ],

    # ---- B5 招生章程（阳光高考统一格式）----
    "charter": [
        "https://gaokao.chsi.com.cn/zsgs/zhangcheng/listVerifedZszc--method-index,ssdm-,yxls-.dhtml",
    ],

    # ---- B3 补充 / B6 分专业组录取分 / B4 选科要求（掌上高考数据接口）----
    #   接口 apidata/api/gk/score/province：按「招生省份=江西」(local_province_id=36)
    #   逐年分页；一条记录 = 某校某专业组在某科类/批次的投档线/最低分/最低位次/选科/计划数。
    "group_admission": [
        "https://api.eol.cn/gkcx/api/",
    ],

    # ---- B7 征集志愿（省考试院「通知公告」栏目，正文 + .xls 附件统计表）----
    "supplement": [
        # 2026 各批次缺额院校网上征集志愿填报说明（附件＝缺额院校专业组及专业统计表）
        "https://www.jxeea.cn/jxsjyksy/tzgg92/content/content_2086509143188119552.html",
        "https://www.jxeea.cn/jxsjyksy/tzgg92/content/content_2085019746387173376.html",
        "https://www.jxeea.cn/jxsjyksy/tzgg92/content/content_2082778172809191424.html",
        "https://www.jxeea.cn/jxsjyksy/tzgg92/content/content_2079987570912698368.html",
        "https://www.jxeea.cn/jxsjyksy/tzgg92/content/content_2076698556566773760.html",
    ],

    # ---- B8 院校画像（掌上高考院校库接口，全国院校）----
    "profile": [
        "https://api.eol.cn/gkcx/api/",
    ],
}

# ---------------------------------------------------------------------------
# 三、字段映射（模块 → 字段 → 来源 / URL / 解析方式）
#     对应爬取清单的逐项要求；`python -m data.jiangxi.run --fieldmap` 可打印。
# ---------------------------------------------------------------------------
FIELD_MAP: list[dict] = [
    {
        "module": "A1", "doc_type": "batch_score_line", "title": "批次录取控制分数线（省控线）",
        "source": "江西省教育考试院 / 中国教育在线·掌上高考",
        "urls": URLS["batch_line"],
        "parse": "① CSS: 正文/表格 table tr -> 批次文本；② Regex 兜底：'(本科批)[^。]{0,60}(历史类|物理类)(\\d{3})分'",
        "fields": [
            {"name": "province", "desc": "省份（江西）", "selector": "常量"},
            {"name": "year", "desc": "年份", "selector": "URL/标题解析"},
            {"name": "batch", "desc": "批次", "selector": "table tr td:nth-child(1) / 正文正则"},
            {"name": "subject_type", "desc": "科类", "selector": "同批次行内正则"},
            {"name": "score", "desc": "控制分数线", "selector": "正则捕获的 3 位数字"},
            {"name": "track", "desc": "招生类别（普通/艺术/体育/三校生）", "selector": "段落标题"},
        ],
    },
    {
        "module": "A2", "doc_type": "score_segment", "title": "一分一段统计表",
        "source": "中国教育在线·掌上高考（转载江西省教育考试院）/ 江西省教育考试院",
        "urls": URLS["segment"],
        "parse": "CSS: 主表格 table tr -> [分数, 本段人数, 累计人数]；分数单元格支持 '681及以上'/'665~750'/'448(本科线)'；PDF 源用 pdfplumber.extract_table",
        "fields": [
            {"name": "province", "desc": "省份（江西）", "selector": "常量"},
            {"name": "year", "desc": "年份", "selector": "URL"},
            {"name": "subject_type", "desc": "科类（物理类/历史类/三校生/文史类/理工类）", "selector": "URL/标题"},
            {"name": "score", "desc": "分数", "selector": "table tr td:nth-child(1)"},
            {"name": "score_end", "desc": "区间上界（仅最高分段）", "selector": "同单元格区间解析"},
            {"name": "same_score_count", "desc": "本段人数", "selector": "table tr td:nth-child(2)"},
            {"name": "cumulative_rank", "desc": "累计人数（位次）", "selector": "table tr td:nth-child(3)"},
        ],
    },
    {
        "module": "A3", "doc_type": "province_stat", "title": "报名人数与录取统计",
        "source": "江西省教育考试院（高考新闻发布会）/ 江西省教育厅",
        "urls": URLS["stat"],
        "parse": "CSS: 正文段落；Regex 抽取 '报名总人数为(\\d+\\.\\d+)万''实际参加6月统考(\\d+\\.\\d+)万'",
        "fields": [
            {"name": "year", "desc": "年份", "selector": "标题/正文"},
            {"name": "total_registered", "desc": "报名总人数", "selector": "正则"},
            {"name": "actual_exam", "desc": "实际统考人数", "selector": "正则"},
            {"name": "pre_admitted", "desc": "高职单招提前录取数", "selector": "正则"},
            {"name": "ordinary_count", "desc": "普通类考生数", "selector": "正则"},
            {"name": "sanxiao_count", "desc": "三校生类考生数", "selector": "正则"},
        ],
    },
    {
        "module": "A5", "doc_type": "schedule", "title": "志愿填报与录取日程",
        "source": "江西省教育考试院《录取工作通知》《志愿填报及投档规则》",
        "urls": URLS["schedule"],
        "parse": "CSS: 正文段落；Regex 抽取 '第一次集中填报[^。]{0,80}(\\d+月\\d+日\\s*\\d+:\\d+)[—~-](\\d+月\\d+日\\s*\\d+:\\d+)'",
        "fields": [
            {"name": "stage", "desc": "阶段", "selector": "正文"},
            {"name": "start_time", "desc": "开始时间", "selector": "正则"},
            {"name": "end_time", "desc": "结束时间", "selector": "正则"},
            {"name": "scope", "desc": "适用批次/志愿栏", "selector": "正文"},
        ],
    },
    {
        "module": "A7", "doc_type": "pathway_region", "title": "专项实施区域县名单（国家24/地方全省/高校58/苏区54）",
        "source": "江西省教育厅 / 教育部阳光高考平台",
        "urls": URLS["pathway_region"],
        "parse": "CSS: 正文列表；Regex 逐县抽取；区划码由 seeds + 区划码补全器填充",
        "fields": [
            {"name": "pathway_name", "desc": "专项名称", "selector": "正文小标题"},
            {"name": "province", "desc": "省份（江西）", "selector": "常量"},
            {"name": "city", "desc": "所属设区市", "selector": "正文（xx市：）"},
            {"name": "county_name", "desc": "县/市/区名", "selector": "正文"},
            {"name": "county_code", "desc": "行政区划代码", "selector": "seeds/区划码源"},
            {"name": "scope", "desc": "范围口径（地方专项=全省农村）", "selector": "正文"},
        ],
    },
    {
        "module": "A7", "doc_type": "pathway_eligibility", "title": "专项报考资格规则",
        "source": "江西省教育厅《专项计划招生工作的通知》",
        "urls": URLS["pathway_region"],
        "parse": "CSS: 正文「申报xx考生须同时具备下列N项条件」段落；Regex 拆条",
        "fields": [
            {"name": "pathway_name", "desc": "专项名称", "selector": "小标题"},
            {"name": "province", "desc": "省份", "selector": "常量"},
            {"name": "rule_type", "desc": "规则类型（户籍/学籍/区域/成绩）", "selector": "条文分类"},
            {"name": "rule_desc", "desc": "规则条文", "selector": "正文"},
            {"name": "params", "desc": "结构化参数（jsonb）", "selector": "人工整理"},
        ],
    },
    {
        "module": "B1", "doc_type": "school", "title": "院校基础信息（含省编代码）",
        "source": "教育部阳光高考平台 / 江西省《招生计划》",
        "urls": URLS["school"],
        "parse": "CSS: 列表 div.sch-item -> 名称/所在地/层次；详情页补国标码与官网；省编 4 位代码取自江西计划本",
        "fields": [
            {"name": "name", "desc": "院校全称", "selector": "div.sch-item a / h3"},
            {"name": "code", "desc": "国标院校代码", "selector": "详情页文本"},
            {"name": "province_code", "desc": "江西省编招生代码", "selector": "江西计划本"},
            {"name": "province", "desc": "所在省", "selector": "div.sch-item span"},
            {"name": "city", "desc": "所在市", "selector": "同左"},
            {"name": "level", "desc": "层次（本科/专科）", "selector": "同左"},
            {"name": "type", "desc": "类型（综合/理工…）", "selector": "同左"},
            {"name": "ownership", "desc": "办学性质", "selector": "同左"},
            {"name": "website", "desc": "官网", "selector": "详情页 a"},
        ],
    },
    {
        "module": "B3", "doc_type": "school_major_score", "title": "各批次投档线/录取分（院校专业组）",
        "source": "江西省教育考试院（投档情况公告）/ 教育部阳光高考平台",
        "urls": URLS["admission"],
        "parse": "CSS: 投档表 table tr -> [院校代码, 院校名称, 专业组, 投档最低分, 最低位次]；院校专业组代码从组名列正则抽 '第(\\d+)组'",
        "fields": [
            {"name": "school_name", "desc": "院校名称", "selector": "table tr td:nth-child(2)"},
            {"name": "school_code", "desc": "院校（省编）代码", "selector": "table tr td:nth-child(1)"},
            {"name": "year", "desc": "年份", "selector": "公告标题"},
            {"name": "batch", "desc": "批次", "selector": "公告标题"},
            {"name": "subject_type", "desc": "科类", "selector": "公告标题"},
            {"name": "group_code", "desc": "院校专业组代码", "selector": "组名列正则"},
            {"name": "group_name", "desc": "院校专业组名称", "selector": "组名列"},
            {"name": "min_score", "desc": "投档最低分/最低录取分", "selector": "table tr td:nth-child(n)"},
            {"name": "min_rank", "desc": "最低位次", "selector": "同表/一分一段换算"},
            {"name": "plan_count", "desc": "招生计划数", "selector": "同表/计划本"},
        ],
    },
    {
        "module": "B5", "doc_type": "enrollment_rule", "title": "招生章程（校级选科/体检/外语要求）",
        "source": "教育部阳光高考平台·招生章程",
        "urls": URLS["charter"],
        "parse": "CSS: 章程详情页正文 div.content；Regex 抽选科/体检/外语要求段落",
        "fields": [
            {"name": "school_name", "desc": "院校", "selector": "标题"},
            {"name": "year", "desc": "年份", "selector": "标题"},
            {"name": "content", "desc": "章程全文", "selector": "div.content"},
            {"name": "subject_req", "desc": "选科要求", "selector": "正文正则"},
            {"name": "health_req", "desc": "体检要求", "selector": "正文正则"},
            {"name": "foreign_lang_req", "desc": "外语语种要求", "selector": "正文正则"},
        ],
    },
    {
        "module": "A4", "doc_type": "enroll_plan_total", "title": "招生计划总量（分批次/科类）",
        "source": "江西省教育考试院（录取工作通知）/ 掌上高考录取数据聚合",
        "urls": URLS["plan_summary"],
        "parse": "公告正文正则抽计划数；无官方总量时由专业组计划数（plan_count）聚合，标注 non-official",
        "fields": [
            {"name": "year", "desc": "年份", "selector": "公告标题/接口 year"},
            {"name": "batch", "desc": "批次", "selector": "公告正文"},
            {"name": "subject_type", "desc": "科类", "selector": "公告正文"},
            {"name": "plan_total", "desc": "计划总数", "selector": "正文正则/聚合"},
            {"name": "note", "desc": "口径备注（官方/非官方）", "selector": "—"},
        ],
    },
    {
        "module": "B2", "doc_type": "school_plan", "title": "在赣招生计划（分专业组/专业）",
        "source": "江西省教育考试院征集志愿公告附件（缺额院校专业组及专业统计表 .xls）",
        "urls": URLS["supplement"],
        "parse": "附件 .xls（OLE2）→ xlrd 抽表；列 = 院校代码|院校名称|专业组|专业|缺额计划数",
        "fields": [
            {"name": "school_name", "desc": "院校名称", "selector": ".xls 表列"},
            {"name": "school_code", "desc": "院校代码", "selector": ".xls 表列"},
            {"name": "group_code", "desc": "院校专业组", "selector": ".xls 表列"},
            {"name": "major_name", "desc": "专业名称", "selector": ".xls 表列"},
            {"name": "plan_count", "desc": "计划（缺额）数", "selector": ".xls 表列"},
            {"name": "batch", "desc": "批次", "selector": "公告标题"},
            {"name": "subject_type", "desc": "科类", "selector": "公告标题/表列"},
        ],
    },
    {
        "module": "B4", "doc_type": "subject_requirement", "title": "院校专业组选科要求",
        "source": "掌上高考数据接口 apidata/api/gk/score/province（招生省=江西）",
        "urls": URLS["group_admission"],
        "parse": "JSON data.item[] → 每校每专业组一行：sg_name(专业组) + sg_info(选科要求) + sg_fxk/sg_sxk(首选/再选码)",
        "fields": [
            {"name": "school_name", "desc": "院校名称", "selector": "item.name"},
            {"name": "group_name", "desc": "院校专业组", "selector": "item.sg_name"},
            {"name": "subject_req", "desc": "选科要求（文字）", "selector": "item.sg_info"},
            {"name": "first_require", "desc": "首选科目要求", "selector": "item.sg_fxk"},
            {"name": "second_require", "desc": "再选科目要求", "selector": "item.sg_sxk"},
            {"name": "subject_type", "desc": "科类", "selector": "item.local_type_name"},
            {"name": "year", "desc": "年份", "selector": "item.year"},
        ],
    },
    {
        "module": "B6", "doc_type": "group_admission", "title": "院校专业组投档/录取分（含最低位次）",
        "source": "掌上高考数据接口 apidata/api/gk/score/province（招生省=江西）",
        "urls": URLS["group_admission"],
        "parse": "JSON data.item[]；投档线 filing、最低分 min、最低位次 min_section、省控线 proscore、计划数 num",
        "fields": [
            {"name": "school_name", "desc": "院校名称", "selector": "item.name"},
            {"name": "group_name", "desc": "院校专业组", "selector": "item.sg_name"},
            {"name": "year", "desc": "年份", "selector": "item.year"},
            {"name": "batch", "desc": "批次", "selector": "item.local_batch_name"},
            {"name": "subject_type", "desc": "科类", "selector": "item.local_type_name"},
            {"name": "min_score", "desc": "最低分", "selector": "item.min"},
            {"name": "filing_score", "desc": "投档线", "selector": "item.filing"},
            {"name": "min_rank", "desc": "最低位次", "selector": "item.min_section"},
            {"name": "score_line", "desc": "省控线", "selector": "item.proscore"},
            {"name": "plan_count", "desc": "计划数", "selector": "item.num"},
        ],
    },
    {
        "module": "B7", "doc_type": "supplement", "title": "征集志愿（缺额院校专业组及专业）",
        "source": "江西省教育考试院·通知公告（征集志愿填报说明 + 附件 .xls）",
        "urls": URLS["supplement"],
        "parse": "正文 div#zoom 抽征集时间/规则；附件 .xls → xlrd 抽缺额院校专业组及专业统计表",
        "fields": [
            {"name": "year", "desc": "年份", "selector": "公告标题"},
            {"name": "batch", "desc": "批次", "selector": "公告标题"},
            {"name": "school_name", "desc": "缺额院校", "selector": ".xls 表列"},
            {"name": "group_code", "desc": "专业组", "selector": ".xls 表列"},
            {"name": "major_name", "desc": "缺额专业", "selector": ".xls 表列"},
            {"name": "plan_count", "desc": "缺额计划数", "selector": ".xls 表列"},
            {"name": "collect_time", "desc": "征集时间", "selector": "正文正则"},
        ],
    },
    {
        "module": "B8", "doc_type": "school_profile", "title": "院校画像（层次/标签/学科评估）",
        "source": "掌上高考院校库接口 apidata/api/gk/school/lists（全国院校）",
        "urls": URLS["profile"],
        "parse": "JSON data.item[] → 层次 level_name、类型 type_name、办学 nature_name、双一流/985/211、所在省市",
        "fields": [
            {"name": "school_name", "desc": "院校名称", "selector": "item.name"},
            {"name": "school_code", "desc": "国标代码", "selector": "item.code_enroll"},
            {"name": "province", "desc": "所在省", "selector": "item.province_name"},
            {"name": "city", "desc": "所在市", "selector": "item.city_name"},
            {"name": "level", "desc": "层次", "selector": "item.level_name"},
            {"name": "type", "desc": "类型", "selector": "item.type_name"},
            {"name": "ownership", "desc": "办学性质", "selector": "item.nature_name"},
            {"name": "dual_class", "desc": "双一流", "selector": "item.dual_class_name"},
            {"name": "is_985", "desc": "985", "selector": "item.f985"},
            {"name": "is_211", "desc": "211", "selector": "item.f211"},
        ],
    },
]

# ---------------------------------------------------------------------------
# 四、枚举与归一化（江西新老高考跨年口径）
# ---------------------------------------------------------------------------
# 库表 CHECK 为 文科|理科|历史类|物理类|综合；江西另有「三校生」，
# 入库前需三方确认后扩 CHECK（未扩前可把 三校生 映射为 综合）。
VALID_SUBJECTS = {"文科", "理科", "历史类", "物理类", "三校生", "综合"}

SUBJECT_ALIASES: dict[str, str] = {
    "文史类": "文科", "文史": "文科", "文科": "文科",
    "理工类": "理科", "理工": "理科", "理科": "理科",
    "物理类": "物理类", "物理科目组": "物理类", "物理": "物理类",
    "历史类": "历史类", "历史科目组": "历史类", "历史": "历史类",
    "三校生类": "三校生", "三校生": "三校生",
    "综合": "综合", "综合改革": "综合",
}

BATCH_ALIASES: dict[str, str] = {
    "提前本科批": "提前本科批", "提前本科": "提前本科批",
    "本科批": "本科批", "普通本科批": "本科批",
    "提前高职（专科）批": "提前高职(专科)批", "提前高职(专科)批": "提前高职(专科)批",
    "高职（专科）批": "高职(专科)批", "高职(专科)批": "高职(专科)批", "专科批": "高职(专科)批",
    "特殊类型招生": "特殊类型招生", "特殊类型": "特殊类型招生",
    "专项计划": "专项计划",
}

VALID_PATHWAYS = ["国家专项计划", "地方专项计划", "高校专项计划", "苏区专项计划"]


def normalize_subject(raw: str | None) -> str | None:
    """科类归一：文史类→文科、理工类→理科、历史科目组→历史类 …"""
    if not raw:
        return None
    s = str(raw).strip().replace(" ", "")
    if s in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[s]
    # 最长匹配优先：避免「理科」误中「普通类物理科目组」这类子串（物理-科-目）
    for key in sorted(SUBJECT_ALIASES, key=len, reverse=True):
        if key in s:
            return SUBJECT_ALIASES[key]
    return None


def normalize_batch(raw: str | None) -> str:
    """批次名归一（未命中则原样返回）。"""
    if not raw:
        return ""
    b = str(raw).strip().replace(" ", "")
    return BATCH_ALIASES.get(b, b)


def source_of(key: str) -> dict:
    """取数据源登记信息。"""
    return SOURCES[key]

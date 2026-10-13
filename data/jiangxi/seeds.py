"""
江西采集 · 种子数据（人工核对、附官方来源，用于 A7 专项区域/资格 与 A1/A3/A5 交叉校验）。

来源（官方）：
  1. 阳光高考转载·江西省教育厅《关于做好全省2024年普通高校专项计划招生工作的通知》
     https://gaokao.chsi.com.cn/gkxx/zc/ss/202312/20231201/2293172455.html
  2. 上饶市广信区 2026 年普通高考社会考生报名公告（逐县列名，与①一致）
     https://www.srx.gov.cn/gxqjyj/ggzyr/202510/def39889aa9c4478a9c449047ec29e93.shtml

⚠️ county_code（行政区划码）留空，需由区划码源（民政部/国家统计局）补全后回填；
   本文件仅保证「县名 + 所属设区市 + 口径 + 来源」这些已验证事实。
"""
from __future__ import annotations

SEED_SOURCE_NAME = "江西省教育厅（阳光高考平台转载）"
SEED_SOURCE_URL = "https://gaokao.chsi.com.cn/gkxx/zc/ss/202312/20231201/2293172455.html"
SEED_SOURCE_URL_2 = "https://www.srx.gov.cn/gxqjyj/ggzyr/202510/def39889aa9c4478a9c449047ec29e93.shtml"
SEED_YEAR = 2024

# ---------------------------------------------------------------------------
# 一、国家专项计划 · 24 个脱贫县
# ---------------------------------------------------------------------------
NATIONAL_COUNTIES: list[tuple[str, str]] = [
    ("九江市", "修水县"),
    ("萍乡市", "莲花县"),
    ("赣州市", "赣县区"), ("赣州市", "上犹县"), ("赣州市", "安远县"),
    ("赣州市", "宁都县"), ("赣州市", "于都县"), ("赣州市", "兴国县"),
    ("赣州市", "会昌县"), ("赣州市", "寻乌县"), ("赣州市", "石城县"),
    ("赣州市", "瑞金市"), ("赣州市", "南康区"),
    ("上饶市", "广信区"), ("上饶市", "横峰县"), ("上饶市", "余干县"), ("上饶市", "鄱阳县"),
    ("吉安市", "遂川县"), ("吉安市", "万安县"), ("吉安市", "永新县"),
    ("吉安市", "井冈山市"), ("吉安市", "吉安县"),
    ("抚州市", "乐安县"), ("抚州市", "广昌县"),
]

# ---------------------------------------------------------------------------
# 二、高校专项计划 · 58 个县（脱贫县 + 原中央苏区振兴发展规划县）
# ---------------------------------------------------------------------------
COLLEGE_COUNTIES: list[tuple[str, str]] = [
    ("九江市", "修水县"), ("九江市", "都昌县"),
    ("萍乡市", "莲花县"), ("萍乡市", "安源区"), ("萍乡市", "芦溪县"),
    ("新余市", "渝水区"), ("新余市", "分宜县"),
    ("鹰潭市", "余江区"), ("鹰潭市", "贵溪市"),
    ("赣州市", "赣县区"), ("赣州市", "上犹县"), ("赣州市", "安远县"),
    ("赣州市", "宁都县"), ("赣州市", "于都县"), ("赣州市", "兴国县"),
    ("赣州市", "会昌县"), ("赣州市", "寻乌县"), ("赣州市", "石城县"),
    ("赣州市", "瑞金市"), ("赣州市", "南康区"), ("赣州市", "章贡区"),
    ("赣州市", "信丰县"), ("赣州市", "定南县"), ("赣州市", "全南县"),
    ("赣州市", "崇义县"), ("赣州市", "大余县"), ("赣州市", "龙南市"),
    ("宜春市", "袁州区"), ("宜春市", "樟树市"),
    ("上饶市", "广信区"), ("上饶市", "横峰县"), ("上饶市", "余干县"),
    ("上饶市", "鄱阳县"), ("上饶市", "铅山县"), ("上饶市", "弋阳县"), ("上饶市", "广丰区"),
    ("吉安市", "遂川县"), ("吉安市", "万安县"), ("吉安市", "永新县"),
    ("吉安市", "吉安县"), ("吉安市", "吉州区"), ("吉安市", "青原区"),
    ("吉安市", "吉水县"), ("吉安市", "峡江县"), ("吉安市", "永丰县"),
    ("吉安市", "安福县"), ("吉安市", "新干县"), ("吉安市", "泰和县"), ("吉安市", "井冈山市"),
    ("抚州市", "乐安县"), ("抚州市", "广昌县"), ("抚州市", "南城县"),
    ("抚州市", "黎川县"), ("抚州市", "南丰县"), ("抚州市", "崇仁县"),
    ("抚州市", "宜黄县"), ("抚州市", "金溪县"), ("抚州市", "资溪县"),
]

# ---------------------------------------------------------------------------
# 三、苏区专项计划 · 54 个原中央苏区振兴发展规划县（江西特有）
#    = 赣州18 + 吉安13 + 新余2 + 抚州9 + 上饶5 + 宜春2 + 萍乡3 + 鹰潭2
# ---------------------------------------------------------------------------
SOVIET_COUNTIES: list[tuple[str, str]] = [
    # 赣州市（全域 18）
    ("赣州市", "赣县区"), ("赣州市", "上犹县"), ("赣州市", "安远县"),
    ("赣州市", "宁都县"), ("赣州市", "于都县"), ("赣州市", "兴国县"),
    ("赣州市", "会昌县"), ("赣州市", "寻乌县"), ("赣州市", "石城县"),
    ("赣州市", "瑞金市"), ("赣州市", "南康区"), ("赣州市", "章贡区"),
    ("赣州市", "信丰县"), ("赣州市", "定南县"), ("赣州市", "全南县"),
    ("赣州市", "崇义县"), ("赣州市", "大余县"), ("赣州市", "龙南市"),
    # 吉安市（全域 13）
    ("吉安市", "遂川县"), ("吉安市", "万安县"), ("吉安市", "永新县"),
    ("吉安市", "吉安县"), ("吉安市", "吉州区"), ("吉安市", "青原区"),
    ("吉安市", "吉水县"), ("吉安市", "峡江县"), ("吉安市", "永丰县"),
    ("吉安市", "安福县"), ("吉安市", "新干县"), ("吉安市", "泰和县"), ("吉安市", "井冈山市"),
    # 新余市（全域 2）
    ("新余市", "渝水区"), ("新余市", "分宜县"),
    # 抚州市 9
    ("抚州市", "黎川县"), ("抚州市", "广昌县"), ("抚州市", "乐安县"),
    ("抚州市", "宜黄县"), ("抚州市", "崇仁县"), ("抚州市", "南丰县"),
    ("抚州市", "南城县"), ("抚州市", "资溪县"), ("抚州市", "金溪县"),
    # 上饶市 5
    ("上饶市", "广丰区"), ("上饶市", "铅山县"), ("上饶市", "广信区"),
    ("上饶市", "横峰县"), ("上饶市", "弋阳县"),
    # 宜春市 2
    ("宜春市", "袁州区"), ("宜春市", "樟树市"),
    # 萍乡市 3
    ("萍乡市", "安源区"), ("萍乡市", "莲花县"), ("萍乡市", "芦溪县"),
    # 鹰潭市 2
    ("鹰潭市", "余江区"), ("鹰潭市", "贵溪市"),
]

# 地方专项：全省农村地区，官方不划分具体县名单
LOCAL_SCOPE = "全省农村地区（官方不划分具体县名单）"

PATHWAY_REGION_SEEDS: list[dict] = []
for _city, _county in NATIONAL_COUNTIES:
    PATHWAY_REGION_SEEDS.append({
        "pathway_name": "国家专项计划", "province": "江西", "city": _city,
        "county_name": _county, "county_code": "", "scope": "实施区域",
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
    })
for _city, _county in COLLEGE_COUNTIES:
    PATHWAY_REGION_SEEDS.append({
        "pathway_name": "高校专项计划", "province": "江西", "city": _city,
        "county_name": _county, "county_code": "", "scope": "实施区域",
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
    })
for _city, _county in SOVIET_COUNTIES:
    PATHWAY_REGION_SEEDS.append({
        "pathway_name": "苏区专项计划", "province": "江西", "city": _city,
        "county_name": _county, "county_code": "", "scope": "实施区域",
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL_2, "year": 2026,
    })
PATHWAY_REGION_SEEDS.append({
    "pathway_name": "地方专项计划", "province": "江西", "city": "", "county_name": "",
    "county_code": "", "scope": LOCAL_SCOPE,
    "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
})

# ---------------------------------------------------------------------------
# 四、专项报考资格规则（A7）
# ---------------------------------------------------------------------------
PATHWAY_ELIGIBILITY_SEEDS: list[dict] = [
    {
        "pathway_name": "国家专项计划", "province": "江西", "rule_type": "户籍",
        "rule_desc": "本人自高一开始至今具有同一实施县（市、区）户籍，并在当地完成普通高考报名",
        "params": {"household": "实施区域", "household_same_county": True, "from": "高一"},
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
    },
    {
        "pathway_name": "国家专项计划", "province": "江西", "rule_type": "户籍",
        "rule_desc": "本人与父亲或母亲或法定监护人具有同一实施县（市、区）户籍",
        "params": {"parent_same_county": True},
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
    },
    {
        "pathway_name": "国家专项计划", "province": "江西", "rule_type": "学籍",
        "rule_desc": "本人具有户籍地县（市、区）高中连续3年（6学期）学籍并实际就读",
        "params": {"enrollment_years": 3, "actual_study": True},
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
    },
    {
        "pathway_name": "地方专项计划", "province": "江西", "rule_type": "区域",
        "rule_desc": "实施区域为江西省农村地区；本人自高一开始至今具有江西省农村户籍",
        "params": {"scope": "全省农村", "household": "农村"},
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
    },
    {
        "pathway_name": "地方专项计划", "province": "江西", "rule_type": "其他",
        "rule_desc": "已在我省完成当年普通高考报名",
        "params": {"registered": True},
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
    },
    {
        "pathway_name": "高校专项计划", "province": "江西", "rule_type": "户籍",
        "rule_desc": "本人自高一开始至今具有同一实施县（市、区）农村户籍，并在当地完成当年普通高考报名",
        "params": {"household": "农村", "household_same_county": True, "from": "高一"},
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
    },
    {
        "pathway_name": "高校专项计划", "province": "江西", "rule_type": "户籍",
        "rule_desc": "本人与父亲或母亲或法定监护人具有同一实施县（市、区）农村户籍",
        "params": {"household": "农村", "parent_same_county": True},
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
    },
    {
        "pathway_name": "高校专项计划", "province": "江西", "rule_type": "学籍",
        "rule_desc": "本人具有户籍地县（市、区）高中连续3年（6学期）学籍并实际就读",
        "params": {"enrollment_years": 3, "actual_study": True},
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL, "year": SEED_YEAR,
    },
    {
        "pathway_name": "苏区专项计划", "province": "江西", "rule_type": "区域",
        "rule_desc": "在实施区域取得当年普通高考报名资格",
        "params": {"region": "54个原中央苏区振兴发展规划县"},
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL_2, "year": 2026,
    },
    {
        "pathway_name": "苏区专项计划", "province": "江西", "rule_type": "户籍",
        "rule_desc": "本人自高一开始至今具有实施区域户籍",
        "params": {"household_same_region": True, "from": "高一"},
        "source_name": SEED_SOURCE_NAME, "source_url": SEED_SOURCE_URL_2, "year": 2026,
    },
    {
        "pathway_name": "国家专项计划", "province": "江西", "rule_type": "其他",
        "rule_desc": "农村考生认定口径：户口所在地城乡分类代码3位村码首位数=2（如220/210/211），或原农业户口且未发生户籍迁移",
        "params": {"rural_rule": "城乡分类代码首位=2 或 原农业户口未迁移"},
        "source_name": "江西省教育厅（2026年普通高考报名办法）",
        "source_url": "https://jyt.jiangxi.gov.cn/jxjyw/tzgg785/content/content_1976547792451313664.html",
        "year": 2026,
    },
]

# ---------------------------------------------------------------------------
# 五、基准校验值（真实已核实，用于 --selftest 与离线兜底）
# ---------------------------------------------------------------------------
BENCHMARKS: dict = {
    "batch_score_line": [
        # 2024 江西新高考首年（掌上高考/省考试院口径）
        {"year": 2024, "batch": "本科批", "subject_type": "历史类", "score": 463},
        {"year": 2024, "batch": "本科批", "subject_type": "物理类", "score": 448},
        {"year": 2024, "batch": "特殊类型招生", "subject_type": "历史类", "score": 532},
        {"year": 2024, "batch": "特殊类型招生", "subject_type": "物理类", "score": 520},
    ],
    "province_stat": [
        {"year": 2025, "total_registered": 646300, "actual_exam": 567100,
         "pre_admitted": 79200, "ordinary_count": 496300, "sanxiao_count": 70800},
        {"year": 2024, "total_registered": 642100, "actual_exam": 552600},
        {"year": 2023, "total_registered": 625700, "actual_exam": 535700},
    ],
    "schedule": [
        {"year": 2025, "stage": "第一次集中填报（提前本科军、警类）",
         "start_time": "6月26日 9:00", "end_time": "6月27日 17:00",
         "scope": "提前本科军、警类志愿栏"},
        {"year": 2025, "stage": "第二次集中填报（其他志愿）",
         "start_time": "6月30日 9:00", "end_time": "7月4日 17:00",
         "scope": "除提前本科军、警类外的其他志愿"},
    ],
    "benchmark_source": [
        {"name": "中国教育在线·掌上高考（转载江西省教育考试院）",
         "url": "https://gaokao.eol.cn/jiang_xi/dongtai/202406/t20240626_2619478.shtml"},
        {"name": "江西省教育考试院"+"" ,
         "url": "https://www.jxeea.cn/jxsjyksy/gsgg91/content/content_1938140931900411904.html"},
        {"name": "人民网江西频道（高考新闻发布会）",
         "url": "https://jx.people.com.cn/n2/2025/0611/c186330-41255943.html"},
    ],
}

# 一致性自检：种子县数必须与服务口径一致
EXPECTED_REGION_COUNTS = {
    "国家专项计划": 24,
    "高校专项计划": 58,
    "苏区专项计划": 54,
    "地方专项计划": 1,   # 1 条范围 meta 记录（不划县）
}


def region_counts() -> dict[str, int]:
    from collections import Counter
    return dict(Counter(r["pathway_name"] for r in PATHWAY_REGION_SEEDS))

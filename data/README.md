# data/ · 数据工程目录（③ 徐）

> 归属：③ 数据工程 ｜ 建立：2026-10-11（D3）
> 对应任务：`openspec/.../tasks.md` 第 2 节（2.1–2.7）

---

## 目录结构

```
data/
├── README.md                    ← 本文件（2.7 数据管道使用说明）
├── dictionaries/
│   ├── pathways-26.md           ← 26 类升学途径清单（2.4）
│   ├── pathways-26.json         ← 同上，程序可读版
│   ├── pathway-regions.json     ← ★ 专项实施区域表（2.3，入库用，91 行）
│   ├── pathway-regions.csv      ← 同上，人工核对版
│   ├── pathway-eligibility.json ← ★ 资格规则数据（2.3，供 ② 规则引擎消费）
│   └── fields-definition.md     ← 数据字段定义与口径（★ 采集前必读）
├── score_segment/               ← ★ 一分一段表（2.2）
│   ├── score_segment_2026_历史类.json / .csv
│   ├── score_segment_2026_物理类.json / .csv
│   ├── review_2026_历史类.html   ← 人工复核工作台（图 + 解析并排）
│   ├── review_2026_物理类.html
│   └── 一分一段解析报告.md        ← ★ 质量边界与算法说明（必读）
├── sources/
│   ├── source-registry.md       ← 数据源登记表（调研版，含可采集性）
│   ├── source-table.json        ← ★ source 表入库数据（9 条）
│   ├── 采集验证报告.md           ← 各源 HTTP 实测结果
│   └── 区域表构建报告.md         ← 专项区域匹配结果与口径说明
├── scripts/                     ← 采集与清洗脚本（2.1/2.2/2.3/2.6）
│   ├── validate.py              ← 三要素强制校验（2.6）
│   ├── build_region_table.py    ← 专项区域表构建（2.3）
│   ├── check_eligibility_consistency.py ← 规则与区域表一致性校验
│   ├── parse_score_segment.py   ← 一分一段表 OCR 解析（2.2）
│   └── build_review_page.py     ← 复核工作台生成（2.2）
└── samples/
    └── raw/                     ← 小样本包（PDF 原件 + 抽出的页面 JPEG）
```

---

## 当前产出物校验状态（2026-10-11）

| 文件 | 类型 | 记录数 | 校验结果 |
|---|---|---|---|
| `dictionaries/pathways-26.json` | pathway | 26 | ✅ 26/26 通过 |
| `dictionaries/pathway-regions.json` | pathway_region | 91 | ✅ 91/91 通过 |
| `dictionaries/pathway-eligibility.json` | pathway_eligibility | 11 | ✅ 11/11 通过 |
| `sources/source-table.json` | source | 9 | ✅ 9/9 通过 |
| `score_segment/score_segment_2026_历史类.json` | score_segment | 454 | ✅ 454/454 通过（high 441） |
| `score_segment/score_segment_2026_物理类.json` | score_segment | 462 | ✅ 462/462 通过（high 441） |

一致性自检：`check_eligibility_consistency.py` → ✅ 国家专项 38 县与规则 county_codes 完全一致，38 ⊂ 53 成立

> 一分一段表说明：官方只发布**扫描件 PDF（无文本层）**，必须 OCR。
> 详细质量边界、算法与缺口清单见 `score_segment/一分一段解析报告.md`。
> **请勿将 gap 分数当 0 或跳过——那是缺失，须人工补录。**

---

## 校验命令速查

```bash
PY="C:/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe"

# 三要素校验（缺一拒绝入库）
$PY data/scripts/validate.py data/dictionaries/pathway-regions.json --kind pathway_region
$PY data/scripts/validate.py data/dictionaries/pathway-eligibility.json --kind pathway_eligibility
$PY data/scripts/validate.py data/sources/source-table.json --kind source
$PY data/scripts/validate.py data/score_segment/score_segment_2026_历史类.json --kind score_segment

# 重建专项区域表（会在镜像上拉取行政区划代码）
$PY data/scripts/build_region_table.py

# 规则与区域表一致性校验（--fix 可回写）
$PY data/scripts/check_eligibility_consistency.py

# 一分一段表解析（首次加 --refresh 跑 OCR，之后命中缓存秒级重算）
$PY data/scripts/parse_score_segment.py data/samples/raw/imgs --year 2026 --subject 历史类 --refresh
$PY data/scripts/parse_score_segment.py data/samples/raw/imgs --year 2026 --subject 物理类 --refresh

# 生成人工复核工作台
$PY data/scripts/build_review_page.py --year 2026 --subject 历史类
$PY data/scripts/build_review_page.py --year 2026 --subject 物理类
```


---

## 三份前置文档（本目录核心）

| 文档 | 作用 | 对应任务 |
|---|---|---|
| `dictionaries/pathways-26.md` | 26 类升学途径定义，支撑途径字典表 | 2.4 |
| `dictionaries/fields-definition.md` | **字段口径写死**，避免采集返工 | 2.1–2.5 通用 |
| `sources/source-registry.md` | 数据来源登记，含已核实的专项名单 | 2.1–2.5 通用 |
---

## ⚠️ 三条铁律（务必遵守）

### 1. 来源三要素，缺一不入库

```json
{ "source_name": "河南省教育考试院", "source_url": "https://www.haeea.cn/...", "year": 2025 }
```

缺任何一个 → **拒绝入库**（任务 2.6 的校验核心，也是评分红线）。

**严禁**：编数据、用模型补全缺失值、拿别省数据充数。**查不到就标"暂无"。**

### 2. 先定口径，再采数据

任何字段动手采集前，先看 `fields-definition.md`。
「录取分」「位次」这类词各省定义不同，口径不统一会导致全量返工。

### 3. 非官方信息必须标注

生活类信息（`school_life`）必须带 `source_type` 与 `reliability`，
非官方信息默认折叠并显示"仅供参考"。

---

## 采集流程（建议）

```
1. 看 fields-definition.md 确认口径
2. 看 source-registry.md 选数据源
3. 抽样手工抓取，确认可采集 → 存 data/samples/raw/
4. 写脚本 → data/scripts/
5. 输出小样本 → data/samples/
6. 校验三要素（2.6）→ 通过才入库
7. 更新 source-registry.md 的 fetched_at
```

---

## 与其他角色的接口

| 对象 | 约定 |
|---|---|
| ② 后端 | 表结构以第 7 章为准；字段名冲突见 `fields-definition.md` 第五节 |
| ④ 算法 | 切片元数据需含 `province`、`pathway_id`；字段变更三方确认 |

---

## 当前状态

- ✅ 三份前置文档已成稿
- ✅ 专项实施区域名单已核实到官方来源，**已补 `county_code`（53/53 命中）**
- ✅ **`source` 表数据已产出**（9 条，含可采集性结论）
- ✅ **资格规则数据已产出**（11 条，供 ② 规则引擎消费）
- ✅ 校验脚本（2.6）已实现并跑通
- ✅ **一分一段表（2026）已解析**：历史类 454 行 / 物理类 462 行，high 各 441；附复核工作台
- ⏳ 采集脚本待开发：院校库、专业库、录取分、院校画像
- ⏳ 2023–2025 一分一段（任务 2.2 含三年，本次先做 2026 验证方法）
- ⏳ 数据表结构待 D4 由 ② 冻结
- ⚠️ 数据库（PostgreSQL 16 + pgvector）尚未安装

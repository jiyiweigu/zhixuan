# data/ · 数据工程目录（③ 徐）

> 归属：③ 数据工程 ｜ 建立：2026-10-11（D3）
> 对应任务：`openspec/.../tasks.md` 第 2 节（2.1–2.7）

---

## 目录结构

```
data/
├── README.md                    ← 本文件（2.7 数据管道使用说明）
├── DOWNLOAD.md                  ← ★ 数据下载与重建指引（★ 先读）
├── MANIFEST.sha256              ← 已移出数据本体的 SHA256 清单
├── 建表清单与数据来源对照表.md
├── datasets/
│   └── 数据集核验报告.md
├── dictionaries/
│   ├── pathways-26.md           ← 26 类升学途径清单（2.4）
│   ├── pathways-26.json         ← 同上，程序可读版
│   ├── pathway-regions.json     ← ★ 专项实施区域表（2.3，入库用，91 行）
│   ├── pathway-eligibility.json ← ★ 资格规则数据（2.3，供 ② 规则引擎消费）
│   ├── province-exam-rule.json  ← ★ 省份志愿模式规则（8.3，7 条）
│   ├── province-exam-rule.md    ← 同上，说明版
│   └── fields-definition.md     ← 数据字段定义与口径（★ 采集前必读）
├── schools/                     ← ★ 院校库说明（2.1）
│   ├── 软科top300_在豫招生_对照报告.md
│   └── 院校库采集报告.md         ← ★ 来源/口径/待补字段说明
├── school_major_score/          ← ★ 院校专业录取分（首期仅本科批）
│   ├── 录取分导入说明.md
│   └── _major_score_import_report.json  ← 导入报告（渠道数据，未核实）
├── score_segment/               ← ★ 一分一段表（2.2）
│   ├── 一分一段导入说明.md
│   ├── 一分一段解析报告.md        ← ★ 质量边界与算法说明（必读）
│   ├── .ocrcache_*.json         ← OCR 缓存（可重跑）
│   └── _score_segment_import_report.json  ← 导入报告
├── sources/
│   ├── source-registry.md       ← 数据源登记表（调研版，含可采集性）
│   ├── source-table.json        ← ★ source 表入库数据（15 条）
│   ├── 采集验证报告.md           ← 各源 HTTP 实测结果
│   └── 区域表构建报告.md         ← 专项区域匹配结果与口径说明
├── scripts/                     ← 采集与清洗脚本（2.1/2.2/2.3/2.6）
│   ├── validate.py              ← 三要素强制校验（2.6）
│   ├── validate_exam_rule.py    ← 省份志愿模式规则专用校验
│   ├── build_region_table.py    ← 专项区域表构建（2.3）
│   ├── check_eligibility_consistency.py ← 规则与区域表一致性校验
│   ├── fetch_schools.py         ← 在豫招生院校采集（2.1）
│   ├── fetch_moe_schools.py     ← 教育部全国高校名单采集（2.1）
│   ├── fetch_shanghairanking.py ← 软科排名采集（辅助校验）
│   ├── merge_schools.py         ← 院校库合并与字段推断（2.1）
│   ├── import_dataset.py        ← 数据集通用导入（→ staged 中间层）
│   ├── import_major_score.py    ← 院校专业录取分导入（首期本科批）
│   ├── import_score_segment.py  ← 一分一段导入
│   ├── parse_score_segment.py   ← 一分一段表 OCR 解析（2.2）
│   └── build_review_page.py     ← 复核工作台生成（2.2）
└── samples/                     ← 小样本包（② 建表前的样例）
    ├── README.md
    └── *.json                   ← 8 个样本文件（不含 raw/）
```

> ⚠️ **数据本体与考试院官方扫描件已按《数据源与数据获取方案》§5 移出公开仓库（仅本地留档）**：
> 院校专业录取分（`school_major_score/*.json`）、一分一段（`score_segment/score_segment_*.json`、
> `review_*.html`）、院校库 JSON（`schools/*.json`）、考试院一分一段扫描件（`samples/raw/`）
> 因**授权与体积原因**不再随仓库分发。
> 重建指引见 `DOWNLOAD.md`，原始导出物的 SHA256 见 `MANIFEST.sha256`；
> 仓库仅保留**数据字典、导入/校验脚本、来源登记与小样本说明**。

---

## 当前产出物校验状态（2026-10-11）

| 文件 | 类型 | 记录数 | 校验结果 |
|---|---|---|---|
| `dictionaries/pathways-26.json` | pathway | 26 | ✅ 26/26 通过 |
| `dictionaries/pathway-regions.json` | pathway_region | 91 | ✅ 91/91 通过 |
| `dictionaries/pathway-eligibility.json` | pathway_eligibility | 11 | ✅ 11/11 通过 |
| `sources/source-table.json` | source | 15 | ✅ 15/15 通过 |
| `dictionaries/province-exam-rule.json` | province_exam_rule | 7 | ✅ 7/7 通过（1 条 `schema_only`） |
| `score_segment/score_segment_2026_历史类.json`（已移出仓库） | score_segment | 454 | ✅ 454/454 通过（high 441） |
| `score_segment/score_segment_2026_物理类.json`（已移出仓库） | score_segment | 462 | ✅ 462/462 通过（high 441） |
| `schools/schools_merged.json`（已移出仓库） | school | 1367 | ✅ 1367/1367 通过（province/level 100%） |

> 标注「已移出仓库」的文件为留档记录：文件本身已按方案 §5 移出（见 `MANIFEST.sha256`），
> 需先按 `DOWNLOAD.md` 重建后再复跑校验。仓库内仍在的产物可直接校验。

一致性自检：`check_eligibility_consistency.py` → ✅ 国家专项 38 县与规则 county_codes 完全一致，38 ⊂ 53 成立

> 一分一段表说明：官方只发布**扫描件 PDF（无文本层）**，必须 OCR。
> 详细质量边界、算法与缺口清单见 `score_segment/一分一段解析报告.md`。
> **请勿将 gap 分数当 0 或跳过——那是缺失，须人工补录。**

---

## 校验命令速查

```bash
PY="C:/Users/lenovo/.workbuddy/binaries/python/versions/3.13.12/python.exe"

# ⚠️ 凡涉及 *.json 数据本体的命令，需先按 DOWNLOAD.md 重建（数据本体已移出仓库）

# 三要素校验（缺一拒绝入库）
$PY data/scripts/validate.py data/dictionaries/pathway-regions.json --kind pathway_region
$PY data/scripts/validate.py data/dictionaries/pathway-eligibility.json --kind pathway_eligibility
$PY data/scripts/validate.py data/dictionaries/province-exam-rule.json --kind province_exam_rule
$PY data/scripts/validate.py data/sources/source-table.json --kind source
$PY data/scripts/validate.py data/score_segment/score_segment_2026_历史类.json --kind score_segment  # 需先重建

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

# 院校库采集（2.1，两源 + 合并）
$PY data/scripts/fetch_schools.py          # 在豫招生院校（84 页）
$PY data/scripts/fetch_moe_schools.py      # 教育部全国高校（148 页）
$PY data/scripts/merge_schools.py          # 合并 + 字段推断
$PY data/scripts/validate.py data/schools/schools_merged.json --kind school  # 需先重建
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
- ✅ **`source` 表数据已产出**（15 条，含可采集性结论）
- ✅ **资格规则数据已产出**（11 条，供 ② 规则引擎消费）
- ✅ **省份志愿模式规则已产出**（`province-exam-rule.json`，7 条；1 条 `schema_only`）
- ✅ 校验脚本（2.6）已实现并跑通
- ✅ **一分一段表已解析**：2026（历史类 454 / 物理类 462，high 各 441，附复核工作台）+ 2022–2025 河南/江西（渠道数据）
- ✅ **院校专业录取分已导入**：2022/2024/2025 × 河南/江西（首期仅本科批，渠道数据未核实）
- ✅ **院校库（2.1）已采集**：在豫招生本科 **1367 所**，code/province/level 近乎全填
  - ★ 找到**可直连的官方源** `zsjh.haedu.cn`（无 WAF），**无需 Playwright**
  - 待补：`type`/`website`/`intro`（建议并入任务 2.5 院校画像）
- ℹ️ **数据本体已按《数据源与数据获取方案》§5 移出公开仓库**（院校库 JSON、录取分、一分一段、考试院扫描件；仅本地留档）
  - 重建见 `DOWNLOAD.md`，SHA256 清单见 `MANIFEST.sha256`
- ⏳ 专业库（2.1）、院校画像（2.5）
- ⏳ 数据表结构待 D4 由 ② 冻结
- ⚠️ 数据库（PostgreSQL 16 + pgvector）尚未安装

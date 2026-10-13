# data/ · 智选志愿数据采集与入库流水线

> 归属：角色 ③ 数据工程 + 数据库设计（张）｜ 对齐《开发产品书》第 7 章数据模型、第 13 章 D5–D7
> 目标：把河南 2023–2025（含 2026）高考公开数据 **采集 → 清洗 → 校验 → 入库** 到 `db/schema.sql` 定义的 PostgreSQL。
> 数据字典：`db/数据字典_张.md`（字段口径的唯一权威）

---

## 一、目录结构

```
data/
├── run_pipeline.py          # 主入口：采集 → 清洗 → 输出 JSON/CSV →（可选）入库
├── verify.py                # 离线自检（默认不联网），12 项检查（含实库 14 项）
├── requirements.txt         # 依赖
├── collectors/              # 采集器（每类数据一个）
│   ├── base.py              #   HTTP/robots/限速/重试/原文落盘/解析器回退/批次名与科类归一化
│   ├── c_segment.py         #   D-1  一分一段表            → score_segment
│   ├── c_admission.py       #   D-2  院校录取分/投档线     → school_major_score
│   ├── c_pathway_score.py   #   D-4  专项计划录取分        → pathway_score
│   ├── c_school.py          #   D-5  院校库                → school
│   ├── c_batch_line.py      #   D-3  批次控制线（政府公告，主来源）→ batch_score_line
│   ├── c_line.py            #   D-3  批次控制线（平台表，兜底）  → batch_score_line
│   ├── c_policy_doc.py      #   D-16 政策全文 + RAG 切片   → knowledge_doc / knowledge_chunk
│   ├── c_eligibility.py     #   D-13/D-15 专项资格规则 + 时间节点 → pathway_eligibility / pathway_time
│   ├── c_zhangcheng.py      #   D-7/D-17 招生章程          → enrollment_rule / knowledge_doc
│   ├── c_profile.py         #   D-8  院校画像              → school_profile
│   ├── c_discipline.py      #   D-9  学科评估（第四轮+在线增量）→ discipline_eval
│   ├── c_plan.py            #   D-10 招生计划数视图        → school_major_score（并入 admission 组）
│   ├── c_life.py            #   D-11 生活信息（宿舍/食堂/交通/校区）→ school_life
│   ├── c_region.py          #   D-12 专项县名单            → pathway_region
│   └── c_pathway.py         #   D-14/D-6 途径字典 + 专业库 → pathway / major
├── cleaners/normalize.py    # 清洗校验：来源三要素 / 枚举 / 范围 / 去重
├── loaders/pg.py            # 入库：登记来源 → stg_import 暂存 → 正式表 upsert（含专业组聚合）
├── seeds/                   # 人工整理、经核验的种子数据（途径/县名单/录取分）
├── samples/                 # 离线测试样本（HTML）
├── raw/                     # 原始响应落盘（按 源/日期/hash），走网盘不入库
└── output/                  # 清洗结果 JSON + CSV + 校验报告 + 拒收明细
```

---

## 二、快速开始

```bash
# 1. 安装依赖（阿里云源；本机 pip 官方源不通）
python -m pip install -r data/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 2. 离线自检（不联网，验证解析器/清洗器/入库器/schema）
python data/verify.py
#   额外做一次实库连通：
ZHIXUAN_DSN="postgresql://postgres:pwd@localhost:5432/zhixuan" python data/verify.py

# 3. 全量采集（联网，较慢：含 183 校录取分 + 200 校章程）
python data/run_pipeline.py

# 4. 只跑部分（可逗号分隔多个分组）
python data/run_pipeline.py --only batch,policy,eligibility
python data/run_pipeline.py --only zhangcheng --limit 20   # 抽样 20 校章程

# 5. 建库建表 + 入库
createdb -U postgres zhixuan
psql -U postgres -d zhixuan -f db/schema.sql
python data/run_pipeline.py --load-db --dsn "postgresql://postgres:密码@localhost:5432/zhixuan"

# 6. 跳过联网，直接把已产出的 output/*.json 入库/复算校验
python data/run_pipeline.py --from-output --load-db --dsn "postgresql://postgres:密码@localhost:5432/zhixuan"
```

> - `--only` 取值：`segment / school / admission / region / pathway / eligibility / profile / pathway_score / discipline / life / batch / policy / zhangcheng`（可逗号分隔）。
> - `--limit N` 只作用于支持抽样的采集器（admission / profile / zhangcheng / pathway_score / discipline / life）。
> - ⚠️ 单独跑某个分组只会**重写该分组的输出文件**；若多个采集器产出同一 `doc_type`（如 `c_policy_doc` 与 `c_zhangcheng` 都产出 `knowledge_doc`；`c_admission`(D-2) 与 `c_plan`(D-10) 都产出 `school_major_score`），**必须放进同一次 `--only` 运行**，否则后跑的会覆盖先跑的产出。
>   - D-10 已把 `c_plan` 并入 `admission` 组：跑 `--only admission` 会同时得到 D-2 录取分与 D-10 计划数。
>   - D-9/D-11 为独立分组 `discipline` / `life`，与其它组不共用 doc_type，可单独跑。
> - 未配置数据库时，程序只产出 `data/output/*.json|*.csv`，不影响使用。
> - `db/schema.sql` 中 pgvector 为**选装**：未安装时自动跳过 `knowledge_chunk.embedding` 与 HNSW 索引，其余表照常创建。

---

## 三、采集器 → 目标表 对照（16 类）

| 采集器 | 清单编号 | 数据 | 目标表 | 来源 |
|---|---|---|---|---|
| `c_segment` | D-1 | 一分一段表 | `score_segment` | 中国教育在线·掌上高考 |
| `c_admission` | D-2 | 录取分/投档线 | `school_major_score` | 院校子站 + 种子（省考试院） |
| `c_batch_line` | D-3 | 批次控制线 | `batch_score_line` | 河南省政府门户（**主来源**） |
| `c_line` | D-3 | 批次控制线 | `batch_score_line` | 河南省阳光高考信息平台（兜底） |
| `c_pathway_score` | D-4 | 专项计划录取分 | `pathway_score` | 高校招生网分专业组录取分表 + 政府门户公布 |
| `c_school` | D-5 | 院校库（183 所） | `school` | 掌上高考 API |
| `c_pathway` | D-6/D-14 | 专业库 / 26 类途径 | `major` / `pathway` | 教育部专业目录 / 阳光高考 |
| `c_zhangcheng` | D-7/D-17 | 招生章程 | `enrollment_rule` / `knowledge_doc` | 院校子站·招生简章 |
| `c_profile` | D-8 | 院校画像 | `school_profile` | 掌上高考静态数据 `static-data.gaokao.cn` |
| `c_discipline` | D-9 | 学科评估 | `discipline_eval` | 教育部学位中心第四轮汇总 + 掌上高考重点学科 |
| `c_plan` | D-10 | 招生计划数视图 | `school_major_score`（并入 admission 组） | 院校子站「计划数」列聚合到专业组级 |
| `c_life` | D-11 | 生活信息 | `school_life` | 院校简介（宿舍/食堂/交通/校区段落） |
| `c_region` | D-12 | 专项县名单（国家38/高校53；地方=全省农村无县名单） | `pathway_region` | 河南省教育考试院 |
| `c_eligibility` | D-13/D-15 | 资格规则 + 时间节点 | `pathway_eligibility` / `pathway.apply_time` | 政策文件 |
| `c_policy_doc` | D-16 | 政策全文 + RAG 切片 | `knowledge_doc` / `knowledge_chunk` | 省教育厅 / 省政府门户 |

---

## 四、铁律与合规

1. **来源三要素强制**：每条记录必带 `source_name` / `source_url` / `year`，缺一在清洗阶段被拒收并写入 `reject_report.json`。
2. **robots.txt**：`collectors/base.py` 读取并缓存目标站 robots 规则，`Disallow` 路径不抓。
3. **限速与重试**：单站请求间隔 ≥ 2s（含随机抖动），失败指数退避重试 3 次。
4. **不采隐私**：只采公开招生数据，不触碰需登录的成绩/志愿系统。
5. **原始可复现**：所有原始响应落盘 `data/raw/<kind>/<date>/<md5>.html`。
6. **只用 HTTPS**：部分站点对 `http://`（:80）返回 403，采集一律走 `https://`。

### ⚠️ 来源合规说明

- 一分一段、院校库来自 **中国教育在线·掌上高考**（`gaokao.eol.cn` / `api.eol.cn`），登记为 `source_type='公开网络'`。
  该源转载自河南省教育考试院；已如实标注，不算造假。
- **批次线（D-3）主来源已换成政府门户官方发布页**（河南省人民政府/教育厅），`source_type='官方'`，满足"可溯源"要求。
- 省考试院官网 `haeea.cn` 全站 `Disallow`；`gaokao.haedu.cn` 的分数线/一分一段为**图片或 JS 动态加载**（见 §六）。

---

## 五、输出说明

`data/output/`：

| 文件 | 内容 |
|---|---|
| `score_segment.json/.csv` | 一分一段表 |
| `school.json/.csv` | 院校库 |
| `major.json/.csv` | 专业库 |
| `school_major_score.json/.csv` | 院校录取分（入库时聚合为专业组级） |
| `pathway_score.json/.csv` | 专项计划录取分（途径 × 院校专业组） |
| `batch_score_line.json/.csv` | 批次控制分数线 |
| `pathway.json/.csv` | 26 类途径字典 |
| `pathway_region.json/.csv` | 专项县名单 |
| `pathway_eligibility.json/.csv` | 专项资格规则 |
| `pathway_time.json/.csv` | 关键时间节点 |
| `enrollment_rule.json/.csv` | 招生章程 |
| `school_profile.json/.csv` | 院校画像（接口下线，暂空） |
| `knowledge_doc.json/.csv` | 政策/章程/分数线全文 |
| `knowledge_chunk.json/.csv` | 文档切片 |
| `validation_report.json` | 机器可读校验报告 |
| `reject_report.json` | 拒收明细（含 `reject_reason`） |
| `load_report.json` | 入库统计（仅 `--load-db` 时生成） |

> 字段命名：`doc_type` 在**输出/管道层**表示类型标识；
> `knowledge_doc` 的**语义类别**（政策/章程/分数线）存于采集侧 `doc_category`，入库映射到表列 `doc_type`。

---

## 六、实测发现（2026-10-11）

| 源 | 结论 | 影响/处置 |
|---|---|---|
| `gaokao.haedu.cn/scoreline` | 栏目索引页无 `<table>`；子页分数线为**图片**，另有 JS 动态加载（`/content/xxx` 返回"载入中"） | `c_line` 无法静态解析 → D-3 主来源改用政府门户公告页 |
| `api.eol.cn` 院校详情接口 | `code=1064 此版本接口未上线`（列表接口仍可用） | 已改用静态 CDN `static-data.gaokao.cn/www/2.0/school/{id}/info.json`，**D-8 画像恢复可用** |
| `http://`（:80）请求 | 沙箱/网络策略下返回 403 | 采集统一用 `https://`（`c_policy_doc` 已改） |
| `jyt.henan.gov.cn` 部分文章 | JS 渲染壳页 | 已改用可静态解析的省政府门户发布页 |
| `gaokao.haedu.cn` 院校子站 `history_list` | `batch` 只有「本科批」，**不区分专项**；专项信息在院校专业组字段 | D-4 不能靠它 → 改抓高校招生网《在豫分专业组录取分数表》（专项组独立成组） |
| 高校招生网录取分表（如 `zs.huel.edu.cn`） | 静态 HTML 表格，「第301组 ( 国家专项计划 )」明确标注，含最低分+位次 | **D-4 主来源**，已实现并入库 |
| `m.henan.gov.cn` 官方新闻 | 静态文本「国家专项历史类最低录取分598，最高录取分619」 | D-4 补充来源（提供最高分） |

---

## 七、已验证状态（2026-10-11）

**离线自检** `python data/verify.py` → **10/10 通过**（加 `ZHIXUAN_DSN` 做实库连通为 11/11）：

- 模块导入（16 采集器 + 清洗 + 入库）
- 批次控制线解析（2024/2025 抽样值对比官方一致）
- 一分一段解析（含 `710-750` 区间、`535(特招线)` 带批注单元格）
- 批次名/科类归一化（本科批→普通本科批，理工→理科 …）
- **D-4 专项录取分解析**（专业组表格 rowspan 合并 + 官方文本，表格 10 行/专项 6 行、文本 4 条）
- **D-11 生活信息段落抽取**（宿舍/食堂/交通/校区）
- 清洗器拒收缺来源行
- 清洗器 `batch_score_line` / `pathway_time` 业务校验
- 入库器覆盖全部产出 doc_type（16/16）
- 既有产出 来源三要素覆盖率 100%（16 个文件）
- schema 全部表齐全（25/25）

**实库联调（PostgreSQL 16，本机实例）** → 全链路打通：

```
入库：成功 5311 条，失败 0       校验报告 31/31 项通过（100%）
school 213 | major 455 | pathway 26 | pathway_region 132 | pathway_eligibility 13
score_segment 3574 | school_major_score 267（2025 专业组级覆盖 185 校，248 组含计划数）
pathway_score 10 | batch_score_line 18 | enrollment_rule 40 | school_profile 20
discipline_eval 409 | school_life 7 | knowledge_doc 62 | knowledge_chunk 92 | source 995
```
- 铁律验证：各事实表 `source_id IS NULL` 计数 = **0**（含新增 discipline_eval / school_life）。
- 幂等验证：连续两次入库，行数不变（`stg_import` 为追加式导入日志，按批次累积）。
- 自检：`python data/verify.py` → **12/12 通过**；加 `ZHIXUAN_DSN` → **14/14 通过**。
- 批次线数值（官方口径）：2023 一本文547/理514、二本文465/理409；2024 一本文521/理511、二本文428/理396；2025 普本文471/理427、特招文552/理535、专科 185。
- D-4 数值（官方口径）：郑大 2025 国家专项 史598–619 / 物616–642、地方专项 史597–618 / 物600–630；
  河南财经政法大学 2025 国家专项 301组 史579(12692) / 物567(90232)、302组 物583(67120)、
  地方专项 401组 史589(9187) / 物579(72674)、402组 物570(85847)。

---

## 八、尚未覆盖的清单项（TODO）

**D-1 ~ D-17 已全部接入**，无遗留清单项。以下为可选的**深化方向**（非缺口）：

| 方向 | 现状 | 建议做法 |
|---|---|---|
| 第五轮学科评估 | 已采第四轮（2017 公开汇总，409 条） | 官方发布后按同结构增量（唯一键含 `round`） |
| D-11 生活信息扩面 | 7 条（源自院校简介，文本短） | 接入各校《新生入学须知》等更细文本 |
| 江西（第二试点省） | 仅河南 | 采集器已按 `province` 参数化，补来源 URL + 县名单种子即可，不改表 |
| 官方交叉验证源 | 一分一段/院校库来自掌上高考（公开网络） | 补省考试院官方口径交叉核对 |

> `school_profile` 该源未提供住宿费（`school_life`/`accommodation_fee` 留空），如需要可另接来源。

> 现有 `school_major_score` 为院校专业组级；专业级明细在入库时按组聚合（`min_score` 取组内最小、`plan_count` 求和），
> 如需保留专业级须经三方确认后新增 `major_name` 列并调整唯一键（见 `db/数据字典_张.md` §10）。

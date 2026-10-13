# 江西高考数据采集包（`data/jiangxi/`）

对齐《爬取数据清单_江西_张.md》A1–A8 / B1–B8，是继河南之后的**第二试点省**采集器。
采集器按 `province` 参数化，**不改 `db/schema.sql` 表结构**。

> 本包为「独立可运行」实现，复用项目既有 `data/collectors/base.py` 的 robots / 限速 / 重试 / 落盘规范，
> 并额外适配了两个江西特有的现实约束（见 §5）。

---

## 1. 运行环境与依赖

- Python **3.10+**（实测 3.13）
- 依赖（`requirements.txt`）：

  | 库 | 用途 | 是否必需 |
  |---|---|---|
  | `httpx` | HTTP 客户端（限速/重试/自建 SSL 上下文） | 必需 |
  | `beautifulsoup4` | HTML 解析 | 必需 |
  | `lxml` | 高性能解析器 | 可选（缺失自动回退 `html.parser`） |
  | `pdfplumber` | **B3 投档线 PDF 表格抽取** | 可选（缺失则仅采正文分组行） |
  | `xlrd` | **B7 征集志愿 `.xls`（OLE2）附件解析** | 可选（缺失则该模块跳过附件） |
  | `openpyxl` | `.xlsx` 附件解析（备用） | 可选 |

安装：

```bash
python -m pip install -r data/jiangxi/requirements.txt
```

---

## 2. 使用方法

```bash
cd <repo-root>

python -m data.jiangxi.run                  # 全程联网采集（默认全部模块）
python -m data.jiangxi.run --offline        # 不联网：用已核验种子/基准值（可离线复核）
python -m data.jiangxi.run --only admission # 只跑指定模块（逗号分隔可多选）
python -m data.jiangxi.run --limit 100      # 抽样上限（school 等）
python -m data.jiangxi.run --fieldmap       # 打印「字段 → 来源 → URL → 解析方式」对照
python -m data.jiangxi.run --selftest       # 离线自检（解析/校验/种子口径）
python -m data.jiangxi.run --export-seeds   # 导出种子 JSON
```

模块名（`--only` 取值）：`region eligibility pathway batch stat schedule segment
school admission charter group_admission policy special plan subject_req major_score
supplement profile`

> `--sleep <秒>` 可覆盖单站请求间隔（默认 2.0；eol 大数据量任务可调低至 0.8 加速）。

---

## 3. 输出格式

输出目录 `data/jiangxi/output/`：

- `<doc_type>.json` / `<doc_type>.csv` —— 每种数据类型两份（JSON 便于入库，CSV 便于查看）
- `validation_report.json` —— 校验报告（来源三要素覆盖率、口径断言、单调性等）
- `reject_report.json` —— 拒收明细（含 `reject_reason`，如「缺来源」「重复记录（主键=…）」）

每条记录统一带**来源三要素**：`source_name` / `source_url` / `year`，另附 `doc_type`、`row_no`。

本轮联网实采结果（2026-10-13，全 15 类）：

| doc_type | 模块 | 有效 | 说明 |
|---|---|---:|---|
| `group_admission` | B6 | **10752** | 院校专业组投档/录取分（**含最低位次 100%**，2023/2024/2025，1742 所院校） |
| `school_plan` | B2 | **10279** | 专业级招生计划（2026 征集缺额口径，专业组×专业） |
| `supplement` | B7 | **10279** | 征集志愿缺额院校专业组及专业（2026，4 批次） |
| `subject_requirement` | B4 | **7040** | 院校专业组选科要求（1097 所院校） |
| `school_major_score` | B3 | 4843 | 投档线（历史 1593 + 物理 3244 + 三校生 6），含投档位次 |
| `school_profile` | B8 | 2991 | 全国院校画像（层次/类型/办学/双一流·985·211/所在地） |
| `score_segment` | A2 | 1148 | 一分一段（物理 582 + 历史 566），本段人数/累计位次 |
| `pathway_region` | A7 | 137 | 四类专项县名单（国家 24 / 高校 58 / 苏区 54 / 地方全省 1 条口径行） |
| `school` | B1 | 119 | 江西境内高校（本科 52 + 高职 67） |
| `pathway` | A8 | 26 | 特殊类型招生途径字典 |
| `pathway_eligibility` | A7 | 11 | 专项报考资格规则 |
| `knowledge_doc` | A6 | 7 | 招生政策/录取规则全文（喂 RAG） |
| `batch_score_line` | A1 | 4 | 省控线（2024 历史本科 463 / 物理本科 448 / 特招 532·520） |
| `province_stat` | A3 | 3 | 报名/参考人数（2025 646300/567100，2024 642100，2023 625700） |
| `schedule` | A5 | 2 | 志愿填报日程（第一次 6/26–6/27、第二次 6/30–7/4） |

**合计 47641 条有效记录（15 类），校验 26/26 通过，来源三要素覆盖率 100%。**

关键交叉验证：**清华大学 2024 物理类第 503 组 → 681 分 / 位次 34 / 首选物理·再选化学**，
与官方 PDF 投档线（B3）及一分一段累计位次（A2）**三源完全一致**。

### 示例（`batch_score_line.csv`）

```csv
province,year,batch,subject_type,score,track,source_name,source_url
江西,2024,本科批,历史类,463,普通类,江西省教育考试院,...
江西,2024,本科批,物理类,448,普通类,江西省教育考试院,...
```

---

## 4. 字段 → 来源 → 解析方式（可 `--fieldmap` 打印）

| 模块 | 来源站 | 关键 URL | 解析方式 |
|---|---|---|---|
| A1 省控线 | 中国教育在线·掌上高考 / 省考试院 | `gaokao.eol.cn/jiang_xi/dongtai/` | HTML 表格 `table tr` + 正文正则（科类±分数线） |
| A2 一分一段 | 中国教育在线·掌上高考 | `.../t20240626_2619478.shtml`（物理）等 | 长表 `table tr` → 分数/本段人数/累计人数 |
| A3 报名统计 | 省考试院 / 人民网江西 | `jxeea.cn` 公告 | 正文正则（报名/参考人数）+ 已核验基准兜底 |
| A5 志愿日程 | 省考试院 | `.../content/content_1938....html` | 正则「第N次集中填报…6月26日9:00—27日17:00」 |
| A6 政策全文 | 省考试院 / 省教育厅 | `gsgg91/list.html`、`jyt.../tzgg785` | 栏目→文章：`#zoom` 容器正文 |
| A7 专项区域 | 省教育厅（阳光高考转载） | `jyt.jiangxi.gov.cn` + 种子 | 正文「市：县1、县2」逐县抽取 + 已核验种子 |
| A8 特殊类型 | 阳光高考 / 省考试院 | `gaokao.chsi.com.cn/gkxx/zszcgd/` | 列表 + 途径字典 |
| B1 院校库 | 掌上高考 API | `api.eol.cn/gkcx/api?...school/lists&province_id=36` | JSON API 分页 |
| B3 投档线 | **省考试院（原文 + PDF 附件）** | 见 §5 | ①正文分组行正则 ②PDF `pdfplumber.extract_tables` |
| B4 选科要求 | 掌上高考 API | `...score/province&local_province_id=36` | JSON `item.sg_info`/`sg_fxk`/`sg_sxk` |
| B6 专业组投档/录取分 | 掌上高考 API | `...score/province&local_province_id=36&year=…` | JSON `item`：`filing`/`min`/`min_section`/`proscore` |
| B7 征集志愿 | **省考试院通知公告 + `.xls` 附件** | `jxeea.cn/jxsjyksy/tzgg92/content_*.html` | `#zoom` 正文正则 + `xlrd` 抽缺额统计表 |
| B8 院校画像 | 掌上高考 API | `...school/lists`（全国，分页） | JSON `item`：层次/类型/办学/双一流·985·211 |
| B5 招生章程 | 阳光高考 | `.../zhangcheng/listVerifedZszc...` | 列表 + 正文（**受 412 反爬，见 §7**） |

---

## 5. 江西特有约束与工程适配（重点）

### 5.1 省考试院是 Hanweb CMS —— 列表不渲染为 `<a href>`

`jxeea.cn` 栏目页（如 `gsgg91/list.html`）的文章列表是 **JS 模板 + 内联 JSON**：
`listData = { articleList: [ {"title": "...", "urls": "{\"pc\":\"/...content_<id>.html\"}"} ] }`。

- `parsers.extract_hanweb_links()` 直接解析该内联 `articleList`，`fetcher.get_soup()` 会把**未二次序列化的原始 HTML** 挂在 `soup.__dict__["_raw_html"]`，从而让 `extract_links()` 同时支持
  ① 常规 `<a href>` ② Hanweb 内联 JSON。
- **栏目 URL 必须用 `/list.html`**：尾斜杠形式（`/gsgg91/`）会被 WAF 返回 **403**。

### 5.2 站点抖动 + 翻页缺失

- 同一 URL 偶发 `000`（连接被拒）/超时——属**网络抖动**而非硬封；采集器以限速 + 指数退避重试覆盖。
- 该 CMS 的**历史翻页入口未见公开参数**（`?pageNum=`/`list_N.html`/POST 均无效），因此栏目页只能取**第 1 页（15 篇）**。
  → B3 采用**固定原文 URL**（`config.URLS["admission"]`）直达官方投档线文章，规避翻页。
  → 如需按年补齐历史榜单，建议用浏览器控制（headless）或 CMS 内部数据代理。

### 5.3 B3 投档线的双通道解析

1. **正文分组行**：`1.代码1006，清华大学，第103组，669分`
   → 正则 `_BODY_GROUP_PAT`；按「普通类历史/物理科目组」「三校生」**段落标题跟踪 `subject_type`**，
   并**排除艺术/体育类**（后者是综合分，非高考分）。
2. **文章附件 PDF**（完整统计表，162 页）：列 =
   `序号 | 科类 | 院校代码 | 院校名称 | 专业组代号 | 专业组名称 | 投档线 | 最低投档排名 | 备注`
   → `pdfplumber.extract_tables()`；这是覆盖全量院校专业组的权威数据。

正文行与 PDF 行会按业务主键去重（PDF 优先），故 `reject_report` 中的「重复记录」属**正常去重**。

### 5.4 本地缓存（减少重复请求）

`Fetcher(cache=True)` 默认开启：当日已落盘的原始响应（HTML/PDF，键=`md5(url)`）**直接复用**。
首次采集 B3 需下载 2.2MB / 162 页 PDF（约 30 分钟，受站点抖动影响）；
命中缓存后**全流程约 1–3 分钟**。

### 5.5 科类归一「最长匹配」

`物理科目组` 中「物**理科**目组」含子串「理科」，朴素子串匹配会误判为「理科」。
`config.normalize_subject()` 改为**按别名长度降序匹配**，确保 `普通类物理科目组 → 物理类`。

---

## 6. 已知限制 / 待扩展

| 模块 | 状态 | 说明 |
|---|---|---|
| A4 招生计划总量 | 缺口 | **官方未公布单一总量**（计划仅在《招生计划》分册/查询系统中按校发布）；可用 B2 专业组计划（缺额口径）近似，但不作官方事实 |
| B5 招生章程 | 缺口 | 阳光高考对程序化请求返回 **412**（JS 挑战令牌），需浏览器方案或带 Cookie 会话；亦可逐校招生网适配（P2） |
| B2 分专业计划 | 部分 | 已采**缺额批次**的专业级计划（来自 B7 附件）；全量计划本需另行获取 |
| B6 分专业（到「专业」级）录取分 | 部分 | 已采到**专业组级**投档/录取分（含位次）；专业级需逐校或带签名的接口 |

> 已从「骨架」升级为**实采**：B2（缺额口径）/ B4 / B6 / B7 / B8 —— 见 §7。

---

## 7. 本轮补齐（B2/B4/B6/B7/B8）数据源说明

### 7.1 掌上高考数据接口（B3 补充 / B4 / B6）

- 端点：`https://api.eol.cn/gkcx/api/?uri=apidata/api/gk/score/province&local_province_id=36&year=<Y>&page=<P>&size=20`
- 语义：**按「招生省份=江西」**返回某年**所有院校专业组**的录取口径数据；一条 = 一所院校的一个专业组在一个科类/批次的：
  `filing`(投档线) / `min`(最低分) / `min_section`(**最低位次**) / `proscore`(省控线) / `num`(计划数) / `sg_info`(**选科要求**) / `local_batch_name`(批次) / `local_type_name`(科类)。
- **交叉验证**：2024 物理类 清华大学第 503 组 → `min=681 / min_section=34 / 选科=首选物理·再选化学`，
  与官方 PDF 投档线、A2 一分一段累计位次**完全一致**。
- `size` 上限为 **20**（更大值返回空数组）；按年分页（2023≈4499 / 2024≈7588 / 2025≈8224 条）。
- 同一份数据**派生 B4 选科要求**（`subject_requirement` doc_type）。

### 7.2 省考试院「通知公告」+ `.xls` 附件（B2 / B7）

- 征集志愿公告（如《江西省2026年本科缺额院校(第一次)网上征集志愿填报说明》）为**服务端渲染**，正文 `#zoom` 可稳定抽取征集时间与规则；
  附件 `.xls`（**OLE2 真二进制**）用 `xlrd` 解析，表结构：
  `序号 | 科类 | 院校代号 | 院校名称 | 专业组代号 | 专业组名称 | 专业组缺额 | 专业代号 | 专业名称 | 选考科目要求 | 备注`。
- 产出 `supplement`（B7 缺额院校专业组及专业）与 `school_plan`（B2 专业级计划，缺额口径）。

### 7.3 掌上高考院校库（B8）

- 端点：`...school/lists&page=<P>&size=20`（全国 2991 所，分页），字段含层次/类型/办学性质/双一流/985/211/所在省市。
- `f985`/`f211` 为**字符串** `"1"`（是），已用 `_flag()` 兼容。

### 7.4 A4 / B5 为何仍是缺口

- **A4 招生计划总量**：江西**不发布**全省单一计划总量（计划以《招生计划》分册 + 志愿系统按校查询存在）；强行给出会失真，故列为缺口并给出替代口径。
- **B5 招生章程**：阳光高考 `gaokao.chsi.com.cn` 对非浏览器请求返回 **412** 且携带 JS 挑战令牌，纯 HTTP 无法通过；建议用浏览器控制或逐校招生网。

> ⚠️ A3「录取率」官方不一定直接公布，须由「录取数 ÷ 报名数」自算并标注**非官方口径**，
> 不得当作官方事实输出。

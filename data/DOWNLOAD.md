# 数据下载与重建指引（`data/`）

> 归属：③ 数据工程 ｜ 建立：2026-10-13
> 依据：《数据源与数据获取方案》§5（三层落地路径）与 §6.2（合规红线）

本仓库**只保留**数据字典、导入/校验脚本、小样本与来源登记；**数据本体与考试院官方扫描件因授权与体积原因不随仓库分发**，本地留档后从下述渠道重建。
重建完成后用 `MANIFEST.sha256` 核对一致性。缺失的 `source_url` 一律留空并如实标注，**不编造**。

---

## 一、移出仓库的文件是什么

| 目录 | 内容 | 体积 | 性质 |
|---|---|---|---|
| `data/raw/*_enrollment-plan.csv` | 河南+江西 2022–2025 招生计划原始切片（8 个，选科要求解析输入） | 40.1 MB | 渠道数据（Gaokao-Compass-11M） |
| `data/raw/subject-requirement.full.json` | 选科要求数据集完整版（17,492 行，`subject-requirement.json` 超 5MB 上限故仅样本入库） | 9.9 MB | 解析产物（可重跑） |
| `data/school_major_score/school_major_score_*.json` | 院校专业录取分（2022/2024/2025 × 河南/江西，6 个） | 78.8 MB | 渠道数据（Gaokao-Compass-11M） |
| `data/score_segment/score_segment_*.json` | 一分一段表（2022–2025 × 河南/江西 + 2026 历史/物理，10 个） | 8.6 MB | 渠道数据 + 考试院扫描件 OCR |
| `data/score_segment/review_*.html` | 一分一段人工复核工作台（2 个） | 2.9 MB | 解析产物（可重跑） |
| `data/schools/*.json` | 院校库原始/合并数据 —— **队长 2026-10-14 复议后改为随仓库分发**（唯一例外见下） | — | 官方源采集 + 合并产物 |
| `data/samples/raw/` | 考试院官方一分一段扫描件（2 个 PDF + 16 张页面 JPEG） | 4.3 MB | 官方扫描件（版权归考试院） |

合计 **43 个文件、约 100.1 MB**（未压缩）。完整清单与 SHA256 见 `data/MANIFEST.sha256`。

> ⚠️ 上述文件**仅在仓库中移出**，本地保留一份；`.gitignore` 已加规则防止再次误提交。
>
> ✅ **2026-10-14 队长复议（仅院校库）**：`data/schools/` 下的院校库 JSON **改为随仓库分发**。
> 理由：院校库是本作品任务 2.1 的主产物，且采集/合并脚本（`merge_schools`、`build_school_*`、
> `analyze_school_unmatched`、`build_school_aliases`）直接依赖 `schools_raw.json` /
> `moe_schools.json` 等输入，移出后无法离线复跑。
> **唯一例外**：上海软科（ShanghaiRanking）三个榜单 `shanghairanking_2024.json` /
> `shanghai_top300.json` / `shanghai_top300_inhenan.json`（合计 651 KB）属第三方
> 版权数据，仍按上表移出、不入库；重建见 `data/scripts/fetch_shanghairanking.py` 与
> `data/scripts/intersect_shanghai_henan.py`。
> 移出后随仓库分发的院校库 JSON 为 **14 个 / 13.2 MB**。
> `data/MANIFEST.sha256` **未改动**：它仍是这 43 个原始导出物的基线摘要，
> 其中院校库相关文件的摘要现在可直接与仓库内副本校验。

---

## 二、数据从哪来

### 1. Gaokao-Compass-11M（结构化渠道数据集，MIT 许可）

- 数据集 DOI：`doi:10.57967/hf/9882`
- HuggingFace 仓库：`choucsan/Gaokao-Compass-11M`
  - 官方站：<https://huggingface.co/datasets/choucsan/Gaokao-Compass-11M>
  - 国内镜像：<https://hf-mirror.com/datasets/choucsan/Gaokao-Compass-11M>
- 许可：**MIT**（可再分发，但须保留 DOI 引用）
- 覆盖：31 省 × 2017–2025 高考结构化数据（招生计划含选科要求、院校投档线、专业级录取、一分一段表），共约 1132 万行。
- **署名口径（合规红线）**：该数据集仅作**获取渠道**登记；作品内事实结论的 `source_url` 必须指向**省考试院 / 阳光高考**，不得指向本数据集。
- 本目录中由它派生的产物：`score_segment`（2022–2025 河南/江西）、`school_major_score`（2022/2024/2025 河南/江西）。

### 2. 考试院 / 官方源（署名用，权威性背书）

| 来源 | 网址 | 用途 |
|---|---|---|
| 河南省教育考试院 | <https://www.haeea.cn/> | 一分一段、控制线、招生计划（扫描件原件） |
| 河南招生考试信息网 | <https://www.heao.com.cn> | 往年录取统计、分数段 |
| 河南省阳光高考信息平台 | <https://gaokao.haedu.cn/> | 专项区域名单、志愿与投档规则 |
| 河南省阳光高考信息平台（招生计划查询系统） | <https://zsjh.haedu.cn/qwerasd/school> | 在豫招生院校清单（院校代号/国标代码） |
| 教育部阳光高考信息平台 | <https://gaokao.chsi.com.cn/> | 三大专项政策、招生章程 |
| 教育部全国高校名单 | <https://hudong.moe.gov.cn/qggxmd/> | 全国高校名单（补 province/city/level） |
| 江西省教育考试院 | <http://www.jxeea.cn/> | 一分一段、志愿与投档规则 |
| 民政部/国家统计局 行政区划代码 | <https://www.mca.gov.cn/mzsj/xzqh/2023/202301xzqh.html> | 县（区）行政区划码 |

> 各来源的实测可采集性、字段与备注见 `data/sources/source-table.json` 与 `data/sources/source-registry.md`。

---

## 三、怎么重建

### 3.1 下载 Gaokao-Compass-11M（推荐走国内镜像）

```bash
# 选科要求原始切片（河南+江西 2022–2025 enrollment-plan，幂等 + 断点续传）
python data/scripts/fetch_gaokao_compass.py

# 国内网络建议走 HF 镜像
export HF_ENDPOINT=https://hf-mirror.com        # Windows: set HF_ENDPOINT=https://hf-mirror.com

# 方式一：只下需要的省份/年份（推荐，省流量）
curl -L -o data/raw/2024_henan_score-range.csv \
  "$HF_ENDPOINT/datasets/choucsan/Gaokao-Compass-11M/resolve/main/data/2024/henan/score-range.csv"

# 方式二：整仓（约 1.42 GB）
huggingface-cli download choucsan/Gaokao-Compass-11M --repo-type dataset --local-dir data/raw
```

镜像仓库目录结构：`data/{year}/{province}/{table}.csv`；`table ∈ enrollment-plan | school-admission | major-admission | score-range`。
首期只需 **河南、江西 × 2022–2025 × 4 张表**共 24 个文件即可验证链路。

### 3.2 重新生成各产物（脚本均在本目录 `data/scripts/`）

```bash
# 一分一段（渠道数据 → data/score_segment/）
python data/scripts/import_score_segment.py

# 院校专业录取分（渠道数据 → data/school_major_score/）
python data/scripts/import_major_score.py

# 选科要求落盘（解析器 --scan → data/dictionaries/subject-requirement.json 样本
#              + data/raw/subject-requirement.full.json 完整版；须先跑上面的取数脚本）
python data/scripts/parse_subject_req.py --scan

# 选科要求 → 管理端 rule-datasets/import 导入包（→ data/staged/，中间层）
python data/scripts/build_subject_requirement_import.py

# 通用数据集导入（→ data/staged/，中间层，可重跑）
python data/scripts/import_dataset.py

# 院校库（官方源采集 + 合并 → data/schools/）
python data/scripts/fetch_schools.py
python data/scripts/fetch_moe_schools.py
python data/scripts/merge_schools.py

# 一分一段扫描件 OCR 与复核工作台（需先自考试院下载 PDF，解出页面图放 data/samples/raw/imgs/）
python data/scripts/parse_score_segment.py data/samples/raw/imgs --year 2026 --subject 历史类 --refresh
python data/scripts/parse_score_segment.py data/samples/raw/imgs --year 2026 --subject 物理类 --refresh
python data/scripts/build_review_page.py --year 2026 --subject 历史类
python data/scripts/build_review_page.py --year 2026 --subject 物理类
```

> 考试院扫描件（`data/samples/raw/`）无公开直链（河南门户为 JS 挑战型 WAF），须**人工下载官方 PDF** 后解页为 JPEG 放置到 `data/samples/raw/imgs/`，再跑上述解析脚本。

---

## 四、`MANIFEST.sha256` 的用途

`data/MANIFEST.sha256` 记录上述 43 个原始导出物的 **SHA256 摘要与相对路径**（格式 `<sha256>  <相对路径>`，正斜杠、相对仓库根）。

用途：

1. **校验重建结果**：下载/重建后逐文件比对，确认与移出仓库的原始导出物一致（防止镜像更新、传输损坏或拿到错误版本）。
2. **审计留痕**：明确「仓库里少了什么、少了多少」，说明这些文件是**因授权与体积原因主动移出**，而非丢失。
3. **可复现性**：配合本节下载命令与 `data/scripts/`，完整还原数据本体的生成链路。

```bash
# 在仓库根目录执行
sha256sum -c data/MANIFEST.sha256         # Linux/macOS
# Windows（Git Bash 亦可）
certutil -hashfile <文件> SHA256
```

---

## 五、合规声明（《数据源与数据获取方案》§6）

1. **署名到上游**：事实结论的 `source_url` 指向省考试院 / 阳光高考，不指向第三方平台。
2. **不做数据再分发**：掌上高考等页面声明「数据未经授权严禁转载」，其导出物仅在开发期作为获取渠道，不入公开仓库。
3. **保留 DOI**：Gaokao-Compass-11M 为 MIT 许可，再分发须保留 `doi:10.57967/hf/9882` 引用。
4. **官方扫描件**：考试院一分一段扫描件版权归考试院，仅本地留档、随本仓库移出。
5. **敏感个人信息**：体检等档案字段按最小必要采集，不采集身份证号、不上传体检报告原件。

> 仅供参考，最终以省级考试机构公布结果为准。

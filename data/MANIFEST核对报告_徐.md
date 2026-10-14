# `MANIFEST.sha256` 核对报告（数据本体一致性）

> 编制：徐（③ 数据工程）｜ 2026-10-13 ｜ 分支 `feature/xu` @ `6638cbb`（已含 `develop` 合并）
> 核对脚本：`data/scripts/check_manifest.py`（只读、幂等、退出码可用）
> 触发：`develop` `766f10e` 把「数据本体」移出公开仓库，改走 `data/DOWNLOAD.md` + `data/MANIFEST.sha256` 重建校验。
> 本报告回答：**MANIFEST 与本地留档是否一致、不一致的成因是什么、会不会造成实质损失。**

---

## 一、结论速览

`MANIFEST.sha256` 共 **43 条**。核对结果：

| 类别 | 条数 | 含义 |
|---|---|---|
| **一致** | **20** | 磁盘字节与 MANIFEST 完全相同（含全部 18 个考试院扫描件 + 2 个 2026 一分一段 JSON） |
| **枚举/行尾差异** | **16** | 与 develop 基线**语义等价**，仅差 `data_status` 取值（`pending`→`schema_only`）与行尾 |
| **内容演进** | **7** | 与本方分支**真实内容不同**：6 个录取分 + `schools_merged.json` |
| **缺失** | **0** | 20 个原本缺失的文件已从 git 历史恢复（见下节） |

> ✅ 结论：**无内容丢失**。7 条「内容演进」是**本方分支的增强**，不是损坏。

---

## 二、本轮修复的缺口：20 个文件本地缺失

合并 `develop` 时，`766f10e` 的 `git rm` 连工作树一并删除，以下 20 个文件**本地留档**未随之恢复：

| 目录 | 文件 | 数量 |
|---|---|---|
| `data/samples/raw/imgs/` | `历史类_p1–p8.jpg`、`物理类_p1–p8.jpg` | 16 |
| `data/samples/raw/` | `分数段统计表_2026_历史类.pdf`、`…物理类.pdf` | 2 |
| `data/score_segment/` | `review_2026_历史类.html`、`review_2026_物理类.html` | 2 |

**处置**：从 `766f10e^` 用 `git archive` 恢复（**不动索引**；这些路径已被 `.gitignore` 覆盖，不会误入库）。

```bash
git archive "766f10e^" data/samples/raw \
  data/score_segment/review_2026_历史类.html \
  data/score_segment/review_2026_物理类.html | tar -x
```

恢复后 `sha256sum -c` 的「缺失」归零。

---

## 三、⚠️ 关键风险 1：照 `DOWNLOAD.md` 重建会**丢掉录取分的专业维度**

MANIFEST 记录的 6 个 `school_major_score_*.json` 是 **develop 侧版本**（`major_id` 整列为空）。
本方分支在此之上完成了 **B-1（专业代码 → `major_id`）与 B-3 回填**，两者**内容差异显著**：

| 文件 | 行数 | `major_id` 填充（develop → 本方） | `school_id` 挂载（develop → 本方） |
|---|---:|---:|---:|
| `school_major_score_2022_江西` | 18,158 | 0 → **17,797** | 17,269 → 17,782 |
| `school_major_score_2022_河南` | 20,020 | 0 → **19,729** | 19,449 → 19,846 |
| `school_major_score_2024_江西` | 22,781 | 0 → **22,164** | 21,527 → 21,771 |
| `school_major_score_2024_河南` | 31,214 | 0 → **30,575** | 30,800 → 30,908 |
| `school_major_score_2025_江西` | 9,929 | 0 → **9,795** | 9,673 → 9,871 |
| `school_major_score_2025_河南` | 13,934 | 0 → **13,776** | 13,824 → 13,875 |
| **合计** | **116,036** | **0 → 113,836（+113,836）** | **112,542 → 114,053（+1,511）** |

同时本王新增 `major_match` 字段（113,836 行），记录专业匹配方式。

**后果**：若照 `DOWNLOAD.md` §3.2 只做「下载 → 比对 MANIFEST」，得到的是 `major_id` 全空版本
⇒ **`school_major_score.major_id` 的 113,836 行回填全部归零**，B-1/B-3 阻塞项将重新出现。

**根因**：MANIFEST 是「**移出时刻的快照**」，而 `school_major_score` 的**增强由 `data/scripts/import_major_score.py` 现场生成**。
MANIFEST 校验的是**快照**，当前脚本链产出的是**增强版**，两者天然不等。

**建议**（任选其一，需队长定）：

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（推荐）** | 重建后**必须**再跑 `python data/scripts/import_major_score.py`，并用 `check_manifest.py` 识别为「内容演进」而非失败 | 保留增强，校验语义正确 |
| B | 由队长用**增强版**重新生成 `MANIFEST.sha256` | 一劳永逸，但需重下发 100MB 级校验基准 |
| C | 在 `DOWNLOAD.md` 注明「`school_major_score` 须重跑导入脚本，MANIFEST 仅作原始层快照」 | 最小改动，不解决语义混淆 |

---

## 四、⚠️ 关键风险 2：仓库内 `sha256sum -c` 必然「假失败」

本方分支**保留 `data/schools/*.json` 入库**（`PR 前需与队长复议`的特例），而 MANIFEST 记录的是 develop 版本：

- `data/schools/schools_merged.json` —— **内容演进**（含 N21 补录 86 所，1,367 → 1,453）
- `data/schools/schools.json` 等 6 个 —— **枚举差异**（契约 v1.3 迁移）

⇒ 在本分支仓库内直接跑 `sha256sum -c data/MANIFEST.sha256`，**这 7 条必定报错**。
这不是数据损坏，而是「保留入库 + 已完成 v1.3 迁移」的必然结果。

**建议**：开 PR 时同步提请队长**把 `data/schools/*.json` 从 MANIFEST 中摘出**（或按本分支实际内容重算），
否则任何人 clone 本分支后照文档校验都会看到失败，产生误导。

---

## 五、差异性质明细

### 5.1 一致（20 条）

18 个考试院扫描件（PDF/JPEG，二进制不受行尾影响）+ `score_segment_2026_历史类/物理类.json`
（2026 记录仅 6 键、**不含 `data_status`**，故迁移未触及）。

### 5.2 枚举/行尾差异（16 条）

与 develop 基线**去行尾、`data_status` 取值归一后逐字节等价** —— 纯属本轮契约 v1.3 迁移：

- `data/schools/`：`moe_schools.json`、`schools.json`、`schools_raw.json`、
  `shanghai_top300.json`、`shanghai_top300_inhenan.json`、`shanghairanking_2024.json`（6）
- `data/score_segment/`：`score_segment_2022–2025 × 河南/江西`（8）+ `review_2026_*.html`（2）

> 📌 副产物提示：迁移**触及了原始采集产物**（`moe_schools.json`、`shanghairanking_2024.json` 等）。
> 虽然只是 `data_status` 一处、且与全队枚举一致，但严格说「原始层不应被改写」。
> 如需彻底干净，应由生成脚本在写出时即产出 v1.3 取值（已在本轮改造中完成），**历史文件不再回改**。

### 5.3 内容演进（7 条）

- `school_major_score_*.json` ×6（见 §三）
- `schools_merged.json`（含 N21 补录 + v1.3 迁移）

---

## 六、复现

```bash
P=C:/Users/lenovo/.workbuddy/binaries/python/envs/default/Scripts/python.exe

# 概览 + 明细（退出码 0 = 无缺失）
$P data/scripts/check_manifest.py

# 结构化结果（含每条的分类与对照信息），可重跑比对（幂等）
$P data/scripts/check_manifest.py --json data/manifest_check_diag.json

# 严格模式：要求逐字节全等（任何差异即失败；当前预期为 FAIL）
$P data/scripts/check_manifest.py --strict

# 原始校验（需先补回 data/samples/raw/，见 §二）
sha256sum -c data/MANIFEST.sha256
```

脚本判定口径：以 `766f10e^`（develop 移出时内容）为基线，必要时回退 `ab6f2f8`（本方分支合并前基线）；
「仅差行尾与 `data_status` 取值」记 `枚举/行尾差异`，否则记 `内容演进`。

---

## 七、待队长裁定的两条

1. **`MANIFEST` 与「增强版产物」的口径**（§三）：MANIFEST 是原始层快照，还是最终产物校验基准？
   若为后者，需用增强版重算。
2. **`data/schools/*.json` 是否仍列入 MANIFEST**（§四）：本分支保留其入库，与 MANIFEST 记录不符，
   开 PR 时需一并复议。

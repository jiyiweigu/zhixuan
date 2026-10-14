# 两套数据库 Schema 差异对照（③ 数据口径件）

> 生成：2026-10-14 ｜ 作者：徐（③ 数据工程）｜ 性质：**只读分析**——未改动任何分支文件、未改动 `backend/alembic/`
>
> 对比对象：`origin/feature/zhang`（张）的 `db/schema.sql` ｜ vs ｜ 本分支 `feature/xu` 的 Alembic 实库（`zhixuan`，`0007_rule_datasets`）

---

## 背景

「张」是本项目成员，其分支 `origin/feature/zhang`（tip `7df1eb1`）已包含**一整套平行的数据工程实现**：

| 内容 | 规模 |
|---|---|
| 采集/清洗/入库/自检 | `data/collectors/` 17 文件 + `cleaners/normalize.py` + `loaders/pg.py` + `run_pipeline.py`(541 行) + `verify.py`(394 行) |
| 自带 schema | `db/schema.sql`（**25 表**，621 行）+ `db/数据字典_张.md`（字段口径声明为"唯一权威"） |
| 数据产物 | `data/output/` 19 份；`load_report.json` 记 **5,270 行已入库**（183 院校 / 455 专业 / 3,574 一分一段 / 267 录取分） |
| 江西采集包 | `data/jiangxi/`，`15 类 47,641 条`（其 tip 提交） |
| 冲突排查 | `与Trae侧冲突排查_张.md`（自行登记 8 项冲突，C1 明确"由契约负责人（队长）确认"） |

**分叉点 `90d42f29`，未合入 develop 的：契约 v1.3（`data_status` 四值）、数据本体移出（`766f10e`）。**

> 注：张的 `data/README.md` 自称角色为「**③ 数据工程 + 数据库设计**」——与本分支③ 存在工作重叠，该归属需队长明确。

---

## 结论先行

**「把我方数据库发给他的 WorkBuddy 做核实/匹配/导入」这条路技术上行不通**，原因不是信任问题，而是**两套 schema 是两条独立设计线**：

1. 他有一份**自己的 25 表 schema** 和**自己的 loader**（`loaders/pg.py` 按他的表结构 upsert）；
2. 我方实库是 **31 表**（Alembic），表名/列/枚举**均不同**；
3. 让他的 loader 往我方库灌他按 25 表产出的 JSON ⇒ 轻则 `CHECK` 报错，重则**列错位静默污染**；
4. 我方是**学生本机**，且 `zhixuan` 角色是 **PostgreSQL 集群超管**（`rolsuper=true`）——凭据外发等于交出整集群。

**正确做法是「先对齐、再合并」，不是「先给库」。**

> **★ 口径已定（2026-10-14）**：以**本分支 Alembic 31 表**为唯一 schema 口径。
> 张的 25 表不作为落库结构，其 `loaders/pg.py` 不作为导入通道；其数据产物走我方准入链路、**由我方导入**。
> 具体接入映射见 **`data/张分支数据接入规范_徐.md`**（本文档为差异证据，那份为执行规范）。
> ⏳ 待 ② / 队长形式落章。

---
## 1. 结构总览



- 张分支（`db/schema.sql`）：**25 张表**
- 本分支（Alembic 实库）：**31 张表**（含 `alembic_version`，业务表 30）
- 同名表：**21** ｜ 仅张有：**4** ｜ 仅我方有：**9**

### 仅张分支有（我方无对应表）

- `app_user`（9 列）
- `batch_score_line`（8 列）
- `stg_import`（11 列）
- `user_profile`（17 列）

### 仅我方有（张分支无对应表）

- `admission_requirement`（12 列）
- `index_task`（15 列）
- `major_tuition`（13 列）
- `physical_restriction`（13 列）
- `profiles`（37 列）
- `province_exam_rule`（19 列）
- `rule_dataset_status`（10 列）
- `subject_requirement`（14 列）
- `users`（8 列）

---

## 2. 同名表逐列对照

> 类型比对已归一 `text`≡`varchar`、去长度精度；下表「实质类型差异」只保留**语义不同**的列。

| 表 | 张列数 | 我方列数 | 仅张有列 | 仅我方有列 | 实质类型差异 |
|---|---|---|---|---|---|
| `admin_audit_log` | 6 | 9 | 1 | 4 | 4 |
| `admin_user` | 5 | 5 | 0 | 0 | 2 |
| `discipline_eval` | 7 | 8 | 0 | 1 | 4 |
| `enrollment_rule` | 10 | 10 | 0 | 0 | 6 |
| `knowledge_chunk` | 9 | 11 | 0 | 2 | 6 |
| `knowledge_doc` | 11 | 11 | 1 | 1 | 4 |
| `major` | 9 | 17 | 2 | 10 | 3 |
| `pathway` | 12 | 13 | 0 | 1 | 4 |
| `pathway_eligibility` | 8 | 10 | 0 | 2 | 5 |
| `pathway_region` | 7 | 9 | 0 | 2 | 4 |
| `pathway_score` | 16 | 11 | 6 | 1 | 8 |
| `qa_log` | 11 | 11 | 0 | 0 | 4 |
| `review_task` | 9 | 9 | 0 | 0 | 4 |
| `school` | 17 | 12 | 5 | 0 | 3 |
| `school_life` | 11 | 11 | 1 | 1 | 4 |
| `school_major_score` | 17 | 15 | 2 | 0 | 10 |
| `school_profile` | 14 | 13 | 1 | 0 | 7 |
| `score_segment` | 10 | 9 | 2 | 1 | 4 |
| `source` | 8 | 8 | 1 | 1 | 4 |
| `user_favorite` | 5 | 5 | 0 | 0 | 4 |
| `user_plan` | 8 | 7 | 1 | 0 | 5 |

---

## 3. 差异明细

### `admin_audit_log`

- **仅张有列**：`target`
- **仅我方有列**：`admin_username`, `target_type`, `target_id`, `client_ip`
- **类型不一致**：admin_id(张:bigint/我:integer); created_at(张:timestamptz/我:timestamp without time zone); detail(张:jsonb/我:json); id(张:bigserial/我:integer)

### `admin_user`

- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer)

### `discipline_eval`

- **仅我方有列**：`updated_at`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); school_id(张:bigint/我:integer); source_id(张:bigint/我:integer)

### `enrollment_rule`

- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); school_id(张:bigint/我:integer); source_id(张:bigint/我:integer); updated_at(张:timestamptz/我:timestamp without time zone); year(张:smallint/我:integer)

### `knowledge_chunk`

- **仅我方有列**：`embedding`, `updated_at`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); doc_id(张:bigint/我:integer); id(张:bigserial/我:integer); meta(张:jsonb/我:json); pathway_id(张:bigint/我:character varying); source_id(张:bigint/我:integer)

### `knowledge_doc`

- **仅张有列**：`source_id`
- **仅我方有列**：`updated_at`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); pathway_id(张:bigint/我:character varying); year(张:smallint/我:integer)

### `major`

- **仅张有列**：`intro`, `source_id`
- **仅我方有列**：`first_class`, `tuition`, `ownership`, `duration`, `campus`, `is_category`, `single_subject_req`, `language_req`, `gender_req`, `interview_required`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); updated_at(张:timestamptz/我:timestamp without time zone)

### `pathway`

- **仅我方有列**：`year`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:character varying); source_id(张:bigint/我:integer); updated_at(张:timestamptz/我:timestamp without time zone)

### `pathway_eligibility`

- **仅我方有列**：`year`, `updated_at`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); params(张:jsonb/我:json); pathway_id(张:bigint/我:character varying); source_id(张:bigint/我:integer)

### `pathway_region`

- **仅我方有列**：`year`, `updated_at`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); pathway_id(张:bigint/我:character varying); source_id(张:bigint/我:integer)

### `pathway_score`

- **仅张有列**：`batch`, `subject_type`, `group_code`, `group_name`, `max_score`, `admitted_num`
- **仅我方有列**：`updated_at`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); major_id(张:bigint/我:integer); min_score(张:numeric(6/我:integer); pathway_id(张:bigint/我:character varying); school_id(张:bigint/我:integer); source_id(张:bigint/我:integer); year(张:smallint/我:integer)

### `qa_log`

- **类型不一致**：citations(张:jsonb/我:json); created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); user_id(张:bigint/我:character varying)

### `review_task`

- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); qa_log_id(张:bigint/我:integer); reviewed_at(张:timestamptz/我:timestamp without time zone)

### `school`

- **仅张有列**：`is_211`, `is_985`, `dual_class`, `external_id`, `source_id`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); updated_at(张:timestamptz/我:timestamp without time zone)

### `school_life`

- **仅张有列**：`source_id`
- **仅我方有列**：`created_at`
- **类型不一致**：id(张:bigserial/我:integer); school_id(张:bigint/我:integer); updated_at(张:timestamptz/我:timestamp without time zone); year(张:smallint/我:integer)

### `school_major_score`

- **仅张有列**：`group_code`, `group_name`
- **类型不一致**：avg_score(张:numeric(6/我:integer); created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); major_id(张:bigint/我:integer); min_score(张:numeric(6/我:integer); pathway_id(张:bigint/我:character varying); school_id(张:bigint/我:integer); source_id(张:bigint/我:integer); updated_at(张:timestamptz/我:timestamp without time zone); year(张:smallint/我:integer)

### `school_profile`

- **仅张有列**：`source_note`
- **类型不一致**：campus_list(张:jsonb/我:json); created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); master_phd_points(张:jsonb/我:json); school_id(张:bigint/我:integer); source_id(张:bigint/我:integer); updated_at(张:timestamptz/我:timestamp without time zone)

### `score_segment`

- **仅张有列**：`score_end`, `same_score_count`
- **仅我方有列**：`updated_at`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); source_id(张:bigint/我:integer); year(张:smallint/我:integer)

### `source`

- **仅张有列**：`reliability`
- **仅我方有列**：`updated_at`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); fetched_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); year(张:smallint/我:integer)

### `user_favorite`

- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:integer); target_id(张:bigint/我:character varying); user_id(张:bigint/我:character varying)

### `user_plan`

- **仅张有列**：`priority`
- **类型不一致**：created_at(张:timestamptz/我:timestamp without time zone); id(张:bigserial/我:character varying); items(张:jsonb/我:json); updated_at(张:timestamptz/我:timestamp without time zone); user_id(张:bigint/我:character varying)

---

## 4. 枚举（CHECK 约束）对照

### 张分支的枚举原文

- `source`：`source_type IN ('官方','公开网络','投稿')`
- `source`：`reliability IN ('high','medium','low')`
- `pathway`：`priority IN ('P0','P1','P2')`
- `pathway`：`data_status IN ('available','schema_only')`
- `pathway_eligibility`：`rule_type IN ('户籍','学籍','区域','成绩','其他')`
- `school_major_score`：`subject_type IN ('文科','理科','历史类','物理类','综合')`
- `pathway_score`：`subject_type IS NULL OR subject_type IN ('文科','理科','历史类','物理类','综合')`
- `app_user`：`role IN ('user','admin')`
- `app_user`：`status IN ('active','disabled','deleted')`
- `user_profile`：`exam_type IN ('普通','艺术','体育')`
- `user_profile`：`first_subject IN ('物理','历史')`
- `user_profile`：`household_type IN ('城镇','农村')`
- `user_favorite`：`target_type IN ('school','major','school_major')`
- `user_plan`：`strategy IN ('冲','稳','保')`
- `user_plan`：`priority IN ('城市优先','专业优先','院校优先')`
- `qa_log`：`confidence IN ('high','medium','low')`
- `review_task`：`status IN ('pending','approved','corrected','rejected')`
- `stg_import`：`status IN ('new','validated','loaded','rejected')`

### 已知与 develop 契约（v1.3）冲突项

| 字段 | 张分支 | develop 契约 | 冲突性质 |
|---|---|---|---|
| `source_type` | `官方 / 公开网络 / 投稿` | `官方 / 高校官网 / 权威媒体 / 其他` | **枚举取值不相交 2 个**（`公开网络`、`投稿` 非法；`高校官网`、`权威媒体`、`其他` 缺） |
| `data_status` | `available / schema_only` | `available / partial / schema_only / unavailable` | 张分支停在 **v1.2**，缺 `partial`（v1.3 恢复）与 `unavailable` |
| `source.reliability` | 有（`high/medium/low`） | 无此列 | 张分支多一列 |
| 科类 | `subject_type ∈ 文科/理科/历史类/物理类/综合` | 契约用 `first_subject ∈ 物理/历史` | 张已自行登记为 C1 冲突，待队长裁 |

---

## 4.5 结构层结论

1. 两套 schema **不是同一份契约的两个版本，而是两条独立设计线**（分叉点 `90d42f29`，张分支未合入 develop 的 v1.3 与「数据本体移出」）。
2. 只有 1 个同名文件冲突（`data/README.md`），但**表结构层面差异面很大**，不能直接互相灌。
3. 直接「拿我方库 + 他的 loader 导入」会因枚举 CHECK 与表结构不一致而失败或错位。

---

## 5. 处置（**口径已定：以 Alembic 31 表为准**）

### 5.1 不要做的事

| 做法 | 为什么不 |
|---|---|
| 把 `zhixuan` 库连 DSN 发出去 | `zhixuan` 是**集群超管**（`rolsuper/createdb/createrole` 全 true）；要外部连通还需改 `listen_addresses` + `pg_hba.conf`，净新增攻击面 |
| 让他的 loader 直接导入我方库 | 表/列/枚举三处不匹配，**必然错位**（见第 1–3 节） |
| 直接 merge 他分支 | 他会带入：(a) v1.2 契约（`data_status` 仅 2 值）；(b) **数据本体重新入库**（`data/output/` 108 万行），与 `766f10e` 冲突；(c) `data/README.md` 冲突 |

### 5.2 应当做的事（按优先级）

| # | 事项 | 主责 | 说明 |
|---|---|---|---|
| 1 | **裁定唯一 schema 口径**：25 表 vs 31 表 | ② + 队长 | ✅ **已定：Alembic 31 表为准**（2026-10-14；待 ② 形式落章） |
| 2 | **统一枚举**：`source_type` 四值与 `data_status` 四值 | ② + 队长 | 张分支的 `公开网络`/`投稿` 需映射或改造；映射表见接入规范 §4 R2 |
| 3 | **他的 `data/output/*.json` 走我方准入链路** | ③（我） | 见 `data/张分支数据接入规范_徐.md`：**先比后灌**，合格部分由我方导入 |
| 4 | 若确需他"上手跑" | ② | 另建**沙箱库** + **非超管角色**（仅 `CONNECT`+`USAGE`/`CREATE`），**不改 `listen_addresses`**；导完导出 SQL/JSONL 交回审 |
| 5 | 明确「③ 数据工程」归属（徐 / 张 / 分工） | 队长 | 避免两条线继续分叉（**N25b**） |

### 5.3 我可以立刻做的

- 待他提供 `data/output/` 的字段清单后，做一份**逐字段映射表**（他的字段 → 我方哪张表哪个列，哪些对不上）
- 或先对他**已有的** `data/output/*.json`（分支上就有）做一次**准入体检**，直接出「可入 / 需转换 / 拒收」三类清单

> ⚠️ 本文件与 `data/外部数据准入清单_徐.md` 是配套的：那份是**给采集方的问卷**，这份是**给队长的裁决输入**。

---

## 6. 复核命令（可复现）

```bash
# 1. 取他分支的 schema
git show origin/feature/zhang:db/schema.sql > /tmp/zhang_schema.sql

# 2. 取我方实库列（需 PG 在跑）
psql -h 127.0.0.1 -U zhixuan -d zhixuan -t -A -F$'\t' \
  -c "SELECT table_name||'.'||column_name||'.'||data_type||'.'||is_nullable||'.'||coalesce(column_default,'~')
      FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name, ordinal_position;"

# 3. 生成对照：C:\Users\lenovo\.pg16\schema_diff.py
```

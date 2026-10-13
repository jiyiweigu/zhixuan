# db/ · 数据库建库与入库说明

> 归属：角色 ③ 数据工程 + 数据库设计（张）
> 文件：`schema.sql`（DDL，25 张表）、`数据字典_张.md`（字段口径权威）

---

## 一、建库建表

```bash
createdb -U postgres zhixuan
psql -U postgres -d zhixuan -f db/schema.sql
```

- **pgvector 选装**：`schema.sql` 顶部用 `DO ... EXCEPTION` 包裹 `CREATE EXTENSION vector`，
  未安装时只打印 NOTICE 并跳过，其余 25 张表照常创建；装了就自动补上
  `knowledge_chunk.embedding vector(512)` 列与 HNSW 索引。
- 全脚本**幂等**：`CREATE TABLE/INDEX IF NOT EXISTS`，可重复执行。

## 二、把采集数据写入数据库

```bash
# 采集 + 入库（联网）
python data/run_pipeline.py --load-db --dsn "postgresql://postgres:密码@localhost:5432/zhixuan"

# 直接把已产出的 data/output/*.json 入库（离线，免重复联网）
python data/run_pipeline.py --from-output --load-db --dsn "postgresql://postgres:密码@localhost:5432/zhixuan"
```

入库链路：**登记来源 `source` → 写 `stg_import` 暂存（保留原始 JSON）→ 正式表 upsert**。
所有写入按唯一键 upsert，**重复执行结果一致（幂等）**。

## 三、入库结果（本机实测，PostgreSQL 16）

```
入库：成功 5311 条，失败 0       校验报告 31/31 项通过（100%）
school 213 | major 455 | pathway 26 | pathway_region 132 | pathway_eligibility 13
score_segment 3574 | school_major_score 267（2025 专业组级覆盖 185 校，248 组含计划数）
pathway_score 10 | batch_score_line 18 | enrollment_rule 40 | school_profile 20
discipline_eval 409 | school_life 7 | knowledge_doc 62 | knowledge_chunk 92 | source 995
```

## 四、验收 SQL（每日自查）

```sql
-- 铁律：事实表来源缺失必须为 0
SELECT count(*) FROM score_segment       WHERE source_id IS NULL;
SELECT count(*) FROM school_major_score  WHERE source_id IS NULL;
SELECT count(*) FROM pathway_score       WHERE source_id IS NULL;
SELECT count(*) FROM batch_score_line    WHERE source_id IS NULL;
SELECT count(*) FROM knowledge_doc       WHERE source_id IS NULL;

-- 一分一段按年/科类
SELECT year, subject_type, count(*) FROM score_segment GROUP BY 1,2 ORDER BY 1,2;

-- 批次线完整性
SELECT year, count(*) FROM batch_score_line GROUP BY 1 ORDER BY 1;

-- D-4 专项录取分（按途径 × 院校 × 专业组）
SELECT p.name AS pathway, sc.name AS school, ps.subject_type, ps.group_code, ps.min_score
FROM pathway_score ps
JOIN pathway p ON p.id = ps.pathway_id
JOIN school  sc ON sc.id = ps.school_id
ORDER BY p.name, sc.name, ps.group_code NULLS LAST;

-- 来源覆盖率
SELECT s.source_name, count(*) FROM school_major_score m
JOIN source s ON s.id = m.source_id GROUP BY 1 ORDER BY 2 DESC;
```

## 五、本机便携实例（本次联调用，非生产）

本次为验证链路，用 PostgreSQL 16 Windows 便携包在 55432 端口起了一个本地实例：

```bash
# 初始化（一次性）
initdb -D C:/Users/zm/pgtest/data -U postgres --auth=trust --encoding=UTF8 --no-locale
# 启动
pg_ctl -D C:/Users/zm/pgtest/data -o "-p 55432" -l C:/Users/zm/pgtest/pg.log start
# 停止
pg_ctl -D C:/Users/zm/pgtest/data stop
# 连接
psql -h 127.0.0.1 -p 55432 -U postgres -d zhixuan
```

> ⚠️ Windows 下 `psql` 执行含中文字符的 SQL 会因客户端编码报 `invalid byte sequence`，
> 解决：`set PGCLIENTENCODING=UTF8`，且尽量用纯 ASCII 别名，或把 SQL 存成 UTF-8 文件用 `-f`。

## 六、已知口径

- `school_major_score` 的投档单位是**院校专业组**：入库前把专业级明细聚合到组级
  （`min_score` 取组内最小、`min_rank` 最优、`plan_count` 求和、`avg_score` 均值），
  避免 `major_id` 为 NULL 时多行互相覆盖。保留专业级须经三方确认后加列改键。
- `knowledge_doc.doc_type` 存**语义类别**（政策/章程/分数线）；采集侧字段名为 `doc_category`。
- `stg_import` 为追加式审计日志（按 `batch_no` 累积），事实表幂等。

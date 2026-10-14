# 合并 develop 后自检报告

> 执行人：③ 数据工程（徐）　|　日期：2026-10-14　|　分支：`feature/xu`
> 合并提交：**`e4797cd`**（两父 `b1187e1` + `3132521`）　|　状态：**已推送，远端 = 本地**
> 本报告全程**只读**（唯一一次 DDL 试跑在事务内 `SAVEPOINT` + `ROLLBACK`，库零改动）。

---

## 〇、结论（一句话）

**合并不但成功，而且已经见效**：11 处冲突**全取本方**（主线侧均为本方旧快照）、预演 **0 冲突**、
硬阻塞 **12 → 10**（迁移 0008 已解决 `school_major_score.school_id` 空值阻塞 = **B-3 落地**）。
**但顺手实测出 1 个新硬阻塞**：合并带入的迁移 **0008 有 2 处 PG 不兼容**（Boolean 列默认值写成
`sa.text('0')`），⇒ 本机库现停在 `0007`、分支已到 `0009`，**升级在 PG 上必崩在 0008**。

---

## 一、合并结果

| 项 | 实测 |
|---|---|
| 合并提交 | `e4797cd`（`git rev-list --parents` 确认两父：`b1187e1` + `3132521`） |
| `develop` 是否已成祖先 | ✅ 是 |
| 合并预演（`git merge-tree --write-tree`） | **0 冲突** |
| 落后 / 领先 develop | **0 / 44** |
| 迁移链 | `0007_rule_datasets` → `0008_merge_ready` → `0009_school_major_score_identity` |
| 契约版本 | **v1.3 → v1.4** |
| 远端验证（`git ls-remote`） | 远端 `refs/heads/feature/xu` == 本地 HEAD == `e4797cd` |
| 工作树 | clean |

---

## 二、11 处冲突消解（原则：**全部取本方**）

三方比对（base `7f306d5` / 本方 `b1187e1` / 主线 `3132521`）后确认：
**主线侧这 11 个文件全部来自 `2c510ad`（PR #8，作者 `2626-Ui`）—— 即本方自己的早期快照，非他人新编辑。**

| # | 文件 | 主线侧（旧） | 本方（新，采纳） |
|---|---|---|---|
| 1 | `data/契约裁决请求_徐.md` | 只到旧 N25 | N25–N37 全量 |
| 2 | `data/建库任务清单_徐.md` | 旧「阻塞项清单（9 个）」 | 修订说明 + 合计 140,837 |
| 3 | `data/schema差异对照_徐.md` | §5「建议处置·供队长裁决」 | §5「处置（口径已定：以 Alembic 31 表为准）」 |
| 4 | `data/scripts/check_manifest.py` | 无 `KNOWN_REMOVED` ⇒ 恒 FAIL | 含「已知移出」修复 |
| 5 | `data/scripts/check_schema_alignment.py` | 旧 `RE_COL`（单行截断）+ 旧 `majors.json` 路径 | 括号配对解析 + `major_table_rows.json` |
| 6 | `data/scripts/parse_major_catalog.py` | 含**已废弃枚举** `"data_status": "verified"` | 已清除（契约 v1.3 明令禁用） |
| 7 | `data/dictionaries/pathway-eligibility.json` | 悬空 `pathway_id="general-batch"` | 已按 G1 修为 `normal-batch` |
| 8 | `data/samples/pathway_eligibility.json` | 规则缺 `"year"` | 含 `"year": 2025`（契约：事实数据必带 year） |
| 9 | `data/samples/pathway_region.json` | `province="河南省"` | `province="河南"` + `province_raw="河南省"`（**合 G6**） |
| 10 | `data/samples/school.json` | 10 行 | **12 行**（超集） |
| 11 | `data/samples/school_major_score.json` | 12 行 | **14 行**（超集） |

**校验**：11 个文件解析结果与合并前 `b1187e1` 版本**逐字节一致**（`git hash-object` 比对：一致 11 / 不一致 0）。

---

## 三、本次合并带入（主线新增，无冲突，22 文件 / +3,957 行）

- **迁移**：`0008_merge_ready`、`0009_school_major_score_identity`；
- **契约 v1.4**（§8.10 基础事实表补充列）：
  - 录取分身份列 `group_code` / `major_code` / `major_name` / `exam_system` + 导入键
    `ix_school_major_score_identity`（§8.10.1）；
  - `school.is_985` / `is_211` / `dual_class`；`major.intro`；`score_segment.batch` / `same_score_count`（§8.10.2）；
  - **§8.10.3 两条红线**：① `school_id` 位置耦合 —— 装载必须显式采用数据侧 id 作主键、
    消费侧缺失「跳过并上报」、**绝不降级 NULL**；② 可空 ≠ 可推断。
- **官方导入通道**：`backend/app/services/importers/**` ×11 + `backend/test_importers.py`（PR #12）；
- **数据脚本/字典**：`data/scripts/merge_datasets.py`（1,106 行）、`data/dictionaries/school_tiers.json`；
- 模型与前后端：`base_data.py`、`constraints.py`、`frontend/src/mocks/index.ts`。

---

## 四、全链路自检（13 项）

| # | 检查 | 结果 |
|---|---|---|
| 1 | `check_manifest.py` | ✅ **`[OK]`** 一致 18 ｜ 枚举/行尾 5 ｜ 内容演进 18 ｜ 已知移出 3 ｜ **缺失 0** |
| 2 | `dataset_status.py check` | ✅ 10 份产物 / **11,694 条**一致，**0 处契约禁用枚举** |
| 3 | 口径归一映射 `--check` | ✅ 全覆盖，与规则表 `batch_code` 交叉校验一致 |
| 4 | 途径引用完整性 | ✅ 全部一致 |
| 5 | `validate.py` ×5 | ✅ major / school / school_profile / school_life / enrollment_rule **全部通过** |
| 6 | E3 通道 A（vs 张） | ✅ 一致 **4,721** ｜ 不一致 **0** ｜ 仅我方 0 ｜ 仅张 1（已证伪） |
| 7 | E3 通道 B（vs 官方，offline） | ✅ 一致 **4,719** ｜ 不一致 **0** ｜ 仅官方 **0** ｜ 仅我方(真) 0 ｜ 0 人行 2 |
| 8 | `check_schema_alignment.py` | ⚠️ 硬阻塞 **10**（**全部为 `(type)`，B-4 族**）｜ 软警告 19 |
| 9 | 库内行数 | **140,837**（与合并前逐项一致） |
| 10 | 库内结构 | **88 索引 / 40 外键 / 356 列 / 31 表（17 空）** |
| 11 | 外键悬空 | **40 条逐条检查 → 悬空 0** |
| 12 | `alembic current` / `heads` | `0007_rule_datasets` / **`0009_school_major_score_identity (head)`** |
| 13 | `alembic check` | ❌ `FAILED: Target database is not up to date` —— **预期差异**（库落后 0008/0009，非缺陷） |

### ★ 合并已见效：硬阻塞 12 → 10

`check_schema_alignment.py` 合并前报 **12** 个硬阻塞（11 个 `(type)` + `school_major_score.school_id` 空值），
合并后 **10** 个，**全部为 `(type)`** —— 消失的正是 `school_major_score.school_id` 空值阻塞：
**迁移 0008 已把 `school_id` / `major_id` 放宽为可空 = B-3 落地**。

---

## 五、★★ 新发现：迁移 0008 有 2 处 PG 不兼容（硬阻塞）

### 实测证据（事务内 `SAVEPOINT` 试跑 + `ROLLBACK`，库零改动）

| 语句 | 结果 |
|---|---|
| `ADD COLUMN is_985 boolean NOT NULL DEFAULT 0` | ❌ **报错**：`column "zz_is985" is of type boolean but default expression is of type integer` |
| `ADD COLUMN is_985 boolean NOT NULL DEFAULT false` | ✅ 可执行 |
| `ADD COLUMN major_code varchar(32) NOT NULL DEFAULT ''`（0009） | ✅ 可执行 |
| `ALTER COLUMN school_id DROP NOT NULL` | ✅ 可执行 |

### 根因

`backend/alembic/versions/20261013_0008_merge_ready.py`：

```python
L68:  sa.Column('is_985', sa.Boolean(), nullable=False, server_default=sa.text('0')),
L72:  sa.Column('is_211', sa.Boolean(), nullable=False, server_default=sa.text('0')),
```

`sa.text('0')` 在 PG 上生成 `DEFAULT 0`，而 `is_985/is_211` 是 **boolean** ⇒ PG 拒绝。
**与 `0006` 的 6 处 `sa.text('0')` 属同一类缺陷**（当时补丁改为 `sa.false()`）。

### 精确改法（2 行）

```diff
-        sa.Column('is_985', sa.Boolean(), nullable=False, server_default=sa.text('0')),
+        sa.Column('is_985', sa.Boolean(), nullable=False, server_default=sa.false()),
-        sa.Column('is_211', sa.Boolean(), nullable=False, server_default=sa.text('0')),
+        sa.Column('is_211', sa.Boolean(), nullable=False, server_default=sa.false()),
```

**`0009` 无 PG 问题**（`varchar NOT NULL DEFAULT ''` 实测可执行；`0008` 的 `DROP NOT NULL`、`group_code` 亦可执行）。

### ⇒ PG 兼容补丁范围更新

| 迁移 | PG 不兼容处数 | 状态 |
|---|---|---|
| `0004` | 2（`VARCHAR→JSON` 缺 USING；JSON 列上 `NOT LIKE`） | ⏳ **仍待 ② 落章**（develop 侧未修） |
| `0006` | 6（`sa.text('0')` → `sa.false()`） | 已在既有补丁内 |
| `0008` | **2**（`is_985` / `is_211`） | 🆕 **本次新发现，补丁需扩展** |
| **合计** | **10** | |

---

## 六、当前库状态与差异

| 项 | 值 |
|---|---|
| 行数 / 索引 / 外键 / 列 | 140,837 / 88 / 40 / 356（**合并未波及数据**） |
| `alembic_version` | `0007_rule_datasets`（**落后分支 2 个迁移**） |
| 分支迁移 head | `0009_school_major_score_identity` |
| 空表 | **17 张** |

**注意**：本机库**未**执行 `upgrade`。理由 —— 0008 在 PG 上必崩（见 §五），
且 schema 变更属 **② 主责**，③ 不擅动 `backend/alembic/`。

---

## 七、一键复现

```bash
cd "D:/桌面/zhixuan-xu"
PY=C:/Users/lenovo/.workbuddy/binaries/python/envs/default/Scripts/python.exe

# 合并完整性 / 预演
git rev-list --parents -1 HEAD
git merge-base --is-ancestor origin/develop HEAD && echo "develop 已成祖先"
git merge-tree --write-tree HEAD origin/develop >/dev/null && echo "0 冲突"

# 脚本层自检
$PY data/scripts/check_manifest.py --quiet
$PY data/scripts/dataset_status.py check
$PY data/scripts/check_eligibility_consistency.py
$PY data/scripts/check_schema_alignment.py | grep -E "^⛔|^⚠"

# 库层（PG 需先起库：C:/Users/lenovo/.pg16/pg_service.py start）
cd backend && export ZHIXUAN_DATABASE_URL="postgresql+psycopg://zhixuan:change-me@127.0.0.1:5432/zhixuan"
./.venv/Scripts/python.exe -m alembic current
./.venv/Scripts/python.exe -m alembic heads
./.venv/Scripts/python.exe -m alembic check   # 预期 FAILED：库落后 0008/0009
```

---

## 八、下一步

1. 🆕 **② 将 `0008` 的 2 处 `sa.text('0')` 改为 `sa.false()`**，并把 `0004`/`0006`/`0008` 合并进同一份 PG 兼容补丁；
2. ⏳ **② 应用既有 `data/在线迁移PG兼容补丁_徐.diff`**（覆盖 0004/0006），并扩展至 0008；
3. 补丁落章 → ③ 本地 `upgrade head`（0007→0009）后复跑全链路 + 校验 111,908 行录取分表未被 0008 重建影响；
4. **解锁项**：合并后 `school_major_score` 的**身份列 + 导入键已就位**（契约 §8.10.1），
   原卡在 **B-1 / B-3 / B-6c** 的录取分接入具备条件（B-3 已由 0008 解决）；
   但须遵守 §8.10.3 红线：**`school_id` 必须采用数据侧 1-based 行序号作主键，绝不重编号、绝不降级 NULL**。
5. **回溯点（本地保留）**：`backup/xu-premerge-b1187e1` 分支 + `xu-premerge-b1187e1` 标签。

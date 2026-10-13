# 与 Trae / OpenSpec 侧工作的冲突排查与处理（张）

> 生成：2026-10-12 ｜ 范围：`data/`（爬虫与数据库，本人负责）vs `.trae / .codebuddy / .agents / openspec / docs / backend`（Trae 侧 AI 与团队共享件）
> 原则：**以数据与数据库工作的正确性为主**；共享件（契约、schema）如有冲突，以能承载真实数据的一方为准，并保留对端的合理约定。

---

## 一、结论速览

| # | 冲突点 | 对端（Trae/OpenSpec） | 本人（数据层） | 处置 |
|---|---|---|---|---|
| C1 | **科类字段命名** | `first_subject`（`物理`/`历史`，产品书 6 章 & 契约） | `subject_type`（`物理类`/`历史类`/`文科`/`理科`） | **保留 `subject_type` 为准**，schema 已落地并含 CHECK；契约侧建议增加映射说明（不改本人表） |
| C2 | **问答接口形态** | `GET /api/qa?q=`（契约）vs `POST /api/qa/ask`（产品书 6.3.1） | 数据层不直接暴露接口；RAG 语料按 `knowledge_doc/chunk` 产出 | 属后端/RAG 侧冲突，**不影响数据层**；已在本文登记，交 RAG 负责人 |
| C3 | **采集范围只有河南** | OpenSpec 与《功能描述》要求 **河南 + 江西**（先河南后江西） | 现流水线全部 `province='河南'`（region/batch/segment 均硬编河南） | **本轮以河南为主**（评分主线），江西作为二期；在 README/清单标注"江西待接入"，采集器已按 province 参数化可平滑扩展 |
| C4 | **`--only` 多采集器同产同一 doc_type** | — | `plan`(D-10) 与 `admission`(D-2) 同产 `school_major_score`，单独跑会互相覆盖为空 | **已修复**：把 `collect_plan` 并入 `admission` 组，强制同一次运行 |
| C5 | **学科评估年限口径** | spec 要求可按"学科评估等级"检索（未指定轮次） | 第四轮（2017，公开汇总） | schema 已留 `round` 字段，支持多轮；采集器标 `第四轮`，可增量补第五轮 |
| C6 | **`year` 字段位置** | — | 业务校验器读 `data["year"]`，部分新采集器把 year 只放在 RawRecord | **已修复**：`c_plan` 补 `year` 入 data；`--from-output` 亦保留 year |
| C7 | **`user_profile` / `user_plan` 字段与冻结契约不一致** | `docs/api-contract.md` §2/§5：`household_county`/`enrollment_county`/`household_years`/`enrollment_years`/`parent_household_local`/`special_marks`/`preferences{...}`；`user_plan.strategy=冲/稳/保` + `priority` | 原表用 `home_county`/`school_years`/`has_*_special`/扁平偏好；`user_plan.strategy=('school','major','city')` | **已修复**：schema 全面对齐契约，补兼容迁移块（幂等），并将 `strategy` 语义改为档位 + 新增 `priority` |
| C8 | **D-12 专项实施区域县名单归类错误**（事实性） | 河南省教育考试院/阳光高考：国家专项 38 县、**高校专项 53 县**、**地方专项=全省农村（不划县）** | 原种子误把「53 县」挂到**地方专项**、把 40 县子集挂到高校专项，且含官方名单外的县 | **已修复**：按官方三类分组（26 连片特困 + 12 国贫 + 15 省定）重建种子；国家 38 / 高校 53 / 地方 0 |

---

## 二、逐项说明

### C1 科类字段命名（重要）
- 产品书 6 章数据模型与 `docs/api-contract.md` 用 `first_subject ∈ {物理, 历史}`；
- 本人 `db/schema.sql` 的事实表统一用 `subject_type ∈ {文科, 理科, 历史类, 物理类, 综合}`。
- **判定**：河南 2023–24 为文/理，2025+ 为历史类/物理类，老高考数据必须能落库，故 `subject_type` 是唯一能同时承载 3 年跨度的口径。`first_subject` 只覆盖新高考两年，会丢 2023–24。
- **处置**：数据层保留 `subject_type`；契约层建议在文档加一行「`subject_type` 为全量口径，前端 `first_subject` 为其子集（历史类→历史，物理类→物理）」，由契约负责人（队长）确认后补。

### C2 问答接口（非数据层）
- `open. api-contract.md` → `GET /api/qa?q=`；
- 产品书 6.3.1 → `POST /api/qa/ask`。
- **判定**：这是**后端/RAG 侧**的既有不一致（记忆里第一轮已发群待确认），与爬虫/库表无关。
- **处置**：本文仅登记，不改数据层。

### C3 河南 vs 江西（范围冲突）
- OpenSpec proposal 明确「P0 = 普通批 + 三大专项（**先河南后江西**）」。
- 本人采集器现状：`c_region`/`c_batch_line`/`c_segment` 等以河南为唯一 province；
- **处置**：河南为竞赛主交付（三大专项最典型，评分主线），江西列为二期。已在 `爬取数据清单_张.md` 与 `data/README.md` 标注；采集器内部已按 `province` 参数化，新增江西只需加来源 URL 与县名单种子，**不需改表结构**。

### C4 `--only` 覆盖冲突（已修复）
- 现象：`python run_pipeline.py --only plan` 会把 `school_major_score.json` 覆盖为仅含计划视图（D-2 录取分清零）。
- 根因：D-2 与 D-10 共用 `school_major_score` doc_type，而输出是**按 doc_type 整文件覆写**。
- **修复**：`COLLECTOR_GROUPS["admission"] = [collect_admission, collect_plan]`，二者永远同跑；`DEFAULT_ORDER` 去掉独立 `plan` 组。与记忆里「多采集器产出同一 doc_type 必须同一次 --only」的约定一致。

### C5 学科评估轮次
- spec 要求可按"学科评估等级"检索；`discipline_eval` 表已有 `round` 字段与 `(school_id, discipline_name, round)` 唯一键。
- 首次落地为**第四轮**（2017 年公布，教育部学位中心公开汇总，已核实种子 + 掌上高考在线增量）。第五轮结果尚未全部公开，待官方发布后按同结构增量即可。

### C6 `year` 字段位置（已修复）
- 业务校验器 `_validate_school_major_score` 读 `data.get("year")`；新采集器若只在 `RawRecord.year` 上带年份会被判"year 为空"。
- **修复**：`c_plan` 在 data 内补 `year`；`c_discipline`/`c_life` 亦确保 data 含年份相关字段或使用无 year 校验的 doc_type 校验器。

### C7 `user_profile` / `user_plan` 契约对齐（已修复）
- 冻结契约 `docs/api-contract.md` §2 明确 `user/profile` 的追加字段：`household_county`、`enrollment_county`、`household_years`、`enrollment_years`、`parent_household_local`、`special_marks`（string[]）、`preferences`（对象，含 `priority/preferred_majors/preferred_cities/accept_adjustment`）；§5 明确 `POST /api/plans` 的 `strategy ∈ {冲,稳,保}` 与独立 `priority ∈ {城市优先,专业优先}`。
- 本人原 `db/schema.sql` 用 `home_county`/`home_county_code`/`school_years`/`has_*_special`/扁平 `preferred_*`，且 `user_plan.strategy` 为 `('school','major','city')`——**与契约不符**。
- **判定**：契约是前后端共同冻结的接口口径，**以契约为准**（后端 `PlanRequest.strategy` 也已经是 `冲|稳|保`）。
- **修复**：重写两张表定义对齐契约（`user_profile` 收敛为 17 列；`user_plan` 增 `priority`），并新增**幂等兼容迁移块**（`schema.sql` §10）处理旧库：重命名/补列、合并旧 `preferred_*` 进 `preferences`、删除冗余旧列、重建 `strategy` CHECK。旧库已实测连跑两次零报错。

### C8 专项实施区域县名单归类错误（已修复，事实性纠错）
- **错误**：原 `data/seeds/pathway_regions.json` 把**「53 县」挂到「地方专项计划」**，另把 40 县（含官方名单外的汤阴/获嘉/郏县/临颍/渑池/中牟/巩义等）挂到「高校专项计划」，国家专项 38 县也含官方名单外的唐河/新野/西峡/延津。
- **官方权威口径**（河南省教育考试院 haeea.cn；交叉核对阳光高考附件、郑州大学 2025 高校专项招生简章附件一）：
  - **国家专项 = 38 县**（26 原集中连片特困县 + 12 原国家级扶贫开发重点县）；
  - **高校专项 = 53 县**（38 国家专项县 + 15 原省定扶贫开发重点县）；
  - **地方专项 = 河南省农村地区**，官方**不划分具体县名单**（户籍在河南农村即可）。
- **修复**：按官方三类分组逐条重建种子（含行政代码），国家 38 / 高校 53 / 地方 0（以 `scope` 字段记录口径）；`c_region` 跳过 `_meta`；`c_eligibility` 地方专项「区域」规则由「53 县名单」改为「全省农村」；`run_pipeline` 校验、`verify.py` 新增 D-12 口径检查、数据字典/README/清单/功能描述同步更正；库中 `pathway_region` 清空重载为 91 条。
  - ⚠️ 给团队的提醒：这是**易误读点**——53 县对应的是**高校专项**，不是地方专项；地方专项按"农村户籍"判定。

---

## 三、未冲突但需知会的点
- `.trae/`、`.codebuddy/`、`.agents/` 均为**AI 工具配置目录**，与 `data/`、`db/` 无文件重叠，无物理冲突。
- `.workbuddy/memory/` 与 `data/`、`db/` 已由 `.gitignore` 忽略团队内部笔记与大文件，符合团队共享文件约定。
- OpenSpec 的 7 项能力（user-account / candidate-profile / pathway-eligibility / knowledge-qa / volunteer-plan / school-catalog / knowledge-base-admin）与本人产出的表一一对应，见 `db/数据字典_张.md` 的「capability → 表」映射。

---

## 四、需团队/队长确认的事项（不改则可能返工）
1. **C1 契约增补**：是否在 `api-contract.md` 补 `subject_type ↔ first_subject` 映射说明（属公共文件，按约定须队长改）。
2. **C3 江西排期**：江西是否纳入本轮交付；若纳入，需另开工单，河南主链不动。
3. **C5 第五轮**：若评委/材料需要"最新一轮学科评估"，需等待官方发布后补采。

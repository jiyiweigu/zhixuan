# 智选志愿 API Contract v1.4

> **本文件是前后端与数据库的唯一 DTO 基线。** 契约、产品书、Mock 三者冲突时以本文件为准，
> 并回头修正产品书与 Mock。字段名一律 `snake_case`。
>
> v1.2 变更要点（相对 v1.1）：① 收敛重复定义，删除 `POST /api/plan/generate`；
> ② 6.1 节由「补充说明」改为**逐条可核对的接口表**，与后端实际路由一一对应；
> ③ 新增「路径对照表」附录；④ 统一 `data_status` / `pathway_id` / `batch` /
> `exam_type` 四处跨层词表；⑤ 明确档案可空项一律用 `null`。
>
> **v1.3 变更要点（相对 v1.2）**：`batch_code` 取值由带省份前缀的示例 `HE-UG`
> **更正为不带省份前缀的 `undergraduate_regular`**，并补入完整对照表 —— 后端
> （`app/models/constants.py`）与数据侧（`data/dictionaries/province-exam-rule.json`）
> 已统一为该口径，契约向二者对齐。原示例与 8.3 节自身「各省叫法经 `batch_code`
> 归一后不得再区分」的要求自相矛盾（带前缀会把河南、江西拆成两个键），故予以更正。
>
> **v1.4 变更要点（相对 v1.3）**：新增 **8.10 节**，把录取分事实表
> `school_major_score` 的**身份列**（`group_code` / `major_code` / `major_name` /
> `exam_system`）与**导入键**写入契约，并明确 `school_id` 的位置耦合红线。
> 四列均为第 7 章基础表之外的补充，由后端依据数据工程的实际产物提出、经队长确认。

## 统一约定

- Base URL: `http://localhost:8000`
- 所有路径使用 `/api` 前缀，字段使用 `snake_case`。
- 响应包：`{ code, message, data, trace_id }`。
- 错误码：
  - `1001` 参数错误 / `1002` 未登录 / `1003` 无权限 / `1006` 用户名重复；
  - `1008` 登录失败次数超过阈值（限流）；`1500` 未捕获的服务端异常；
  - `3001` 报考规则数据缺失/未就绪；`4001` 规则记录来源或版本字段不完整。
- **HTTP 状态码约定（两层）**：业务错误统一返回 **HTTP 200**，错误由响应体 `code` 区分
  （前端请求封装对非 2xx 直接抛错，只有 200 才会把响应体交给业务层）；HTTP 层错误
  （404 路由不存在、405 方法不允许）保留原状态码，仅把响应体统一成同一形状，
  此时 `code` 沿用 HTTP 状态码。
- 鉴权：标注 `Auth: yes` 的接口必须带 `Authorization: Bearer <access_token>`
  （登录/注册响应中的 `access_token`）；缺失或不合法返回 `1002`。
  `Auth: optional` 表示带令牌则按登录用户处理，不带/无效则按游客处理。
- 事实数据必须带 `source_name`、`source_url`、`year`。问答必须返回 `citations`
  与 0~1 的 `confidence`；缺引用的结论不得展示。
- 分页包统一为 `{ items, total, page, page_size }`（`page` 从 1 起，`page_size` 上限 100）。

### 跨层词表（唯一取值，禁止各层自造）

| 词表 | 唯一取值 | 说明 |
|---|---|---|
| `data_status` | `available` / `partial` / `schema_only` / `unavailable` | 数据完备度。**禁止**使用 `verified` / `pending` / `mock` 等其它写法；数据工程内部的中间状态必须在此映射后才能出接口。 |
| `pathway_id` | **字符串 slug**（如 `national-plan`、`regular-batch`） | 与 `data/dictionaries/pathways-26.json` 的 `id` 同源。契约 v1.1 曾在第 4 节写作 `number`，v1.2 统一为 `string`。 |
| `batch` | 展示用批次名，首期为 `本科批` | 见第 8.3、8.7 节。 |
| `batch_code` | 机器键（如 `undergraduate_regular`） | 规则表与导入以 `batch_code` 作**唯一键**，`batch` 仅作展示；同一批次的历史别名不得当作不同批次。**不带省份前缀**，取值与别名对照见第 8.3 节。 |
| `exam_type` | `普通` / `艺术` / `体育` | 数据源中的 `category_group` 是**原始列名**，导入时必须映射为 `exam_type`。 |
| 可空档案项 | `null` | `null` = 未提供。服务端**必须**同时接受历史入参 `""` / `"未填"` / `"未知"` 并收敛为 `null`；**禁止**把三态字段的哨兵字符串原样出接口。 |

## 1. 认证

### POST `/api/auth/register`
Auth: no
```json
{"username":"demo","password":"change-me"}
```
```json
{"code":0,"message":"success","data":{"user_id":"u_demo","username":"demo","access_token":"mock-token"},"trace_id":"trace"}
```

### POST `/api/auth/login`
Auth: no；请求同注册，响应同上。
登录失败次数超过阈值时返回 `1008`。

### POST `/api/auth/logout`
Auth: yes；无请求体。吊销当前令牌（按 `jti` 记入失效名单）。
```json
{"code":0,"message":"success","data":null,"trace_id":"trace"}
```

### GET `/api/auth/me`
Auth: yes；返回当前登录用户，供前端刷新页面后恢复登录态。
```json
{"code":0,"message":"success","data":{"user_id":"u_demo","username":"demo"},"trace_id":"trace"}
```

## 2. 考生档案

### GET `/api/user/profile`
Auth: yes
```json
{"code":0,"message":"success","data":{"province":"河南","score":620,"subject_type":"物理类"},"trace_id":"trace"}
```

`data` 为**完整 Profile 对象**，GET 与 PUT 的响应形状一致，均附 `completeness`
（`{ percent, missing: string[] }`）。下表是全量清单；除标注必填者外均可缺省，
缺省时相关判定按「未提供」处理，**不得默认成立**。

**基本（7）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `province` | string | 报考省份 |
| `exam_type` | `普通`/`艺术`/`体育`/null | 招生类型；首期普通本科规则只接受 `普通` |
| `first_subject` | `物理`/`历史`/null | 首选科目 |
| `second_subjects` | string[] | 再选科目，使用项目统一科目字典 |
| `subject_type` | string | 科类，如 `物理类` |
| `score` | number | 高考总分（0~750，越界返回 `1001`） |
| `rank` | number/null | 省内位次 |

**户籍与学籍（8）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `household_type` | `农村`/`城镇`/null | 户籍类型；用于专项计划资格判定。`null` = 未填（**不使用** `未知`） |
| `home_county` | string/null | 户籍所在县（区）**名** |
| `home_county_code` | string/null | 户籍县**行政区划代码**，精确匹配时优先于县名 |
| `school_years` | number/null | 本地学籍年限 |
| `enrollment_county` | string/null | 学籍所在县（区） |
| `household_years` | number/null | 本人当地连续户籍年限 |
| `enrollment_years` | number/null | 当地连续学籍年限 |
| `parent_household_local` | boolean/null | 法定监护人户籍是否在当地 |

**偏好（3）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `preferred_cities` | string[] | 意向城市（有序） |
| `preferred_majors` | string[] | 意向专业类 |
| `tuition_budget` | number/null | 年学费预算（元/年），供第 8.5 节「学费闸门」使用 |

`preferences` 为上述偏好的**方案级镜像**，子字段：`strategy`、`priority`
（`城市优先` / `专业优先` / `院校优先`）、`preferred_majors`、`preferred_provinces`、
`major_adjust`。生成方案时未显式传参的偏好沿用此处已保存值。

**体检（9）**

`color_vision`、`vision_left`、`vision_right`、`height`、`weight`、`hepatitis_b`、
`hearing`、`smell`、`stutter`——取值与校验见第 8.2 节。可空项一律 `null` 表示未填。

**志愿倾向（2）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `batch_preference` | string[] | 意向批次；首期可填 `本科批`，供后续批次扩展 |
| `accept_adjustment` | boolean/null | 档案级默认是否服从专业调剂；实际以方案内每条志愿自身取值为准 |

**派生与元数据（4）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `special_marks` | string[] | 考生自行标记的专项资格，**取值为途径 id**（写入时校验必须是已知途径） |
| `has_national_special` / `has_local_special` / `has_college_special` | boolean | **只读派生字段**，由专项标记与户籍/学籍条件推出，不作为请求入参 |
| `updated_at` | string/null | 最后更新时间，ISO 8601 |
| `completeness` | object | `{ percent, missing[] }`，未填项进 `missing`（产品书 6.1.5 / M2-13） |

> **字段名裁定**：数据侧 `data/dictionaries/fields-definition.md` 曾把
> 「户籍所在县以哪个为准？」列为待确认项。以本表为准：接口与库统一用
> `home_county` / `home_county_code`（Alembic 0006 已把 `household_county`
> 重命名），不再存在 `household_county`。

### PUT `/api/user/profile`
Auth: yes；**增量更新**：未传字段保持原值，显式传 `null` 清空该项。
响应 `data` 为完整 Profile，并附加 `completeness: { percent: number, missing: string[] }`。

### DELETE `/api/user`
Auth: yes；账号注销，需二次校验密码。
```json
{"password":"change-me"}
```
响应 `data` 为 `null`。

## 3. 路径

### GET `/api/pathways`
Auth: no；返回路径数组，每项含 `id`、`name`、`status`、`category`、`priority` 和来源三要素。

可选查询参数：

| 参数 | 取值 | 说明 |
|---|---|---|
| `category` | string | 按类别过滤 |
| `priority` | `P0` / `P1` / `P2` | 按建设优先级过滤 |
| `status` | string | 按可用状态过滤 |

### GET `/api/pathways/{pathway_id}`
Auth: no；单条升学途径详情，`data` 为路径对象（字段同列表项，另含 `citations`、`evaluable`）。
`pathway_id` 为字符串 slug（见词表）。

### GET `/api/pathways/{pathway_id}/regions?province=河南`
Auth: no；返回该途径的**实施区域名单**（仅专项计划类途径有名单）。

```json
{
  "pathway_id": "national-plan",
  "province": "河南",
  "data_status": "schema_only",
  "regions": [{
    "province": "河南", "program": "national", "program_name": "国家专项计划",
    "scope": "county_list", "verified": false, "expected_count": 38,
    "counties": [], "definition": "国家划定的 38 个县……",
    "citation": {"source_name":"官方文件名称","source_url":"https://example.gov.cn/rule","year":2026}
  }],
  "citations": [{"source_name":"官方文件名称","source_url":"https://example.gov.cn/rule","year":2026}],
  "missing_rule_sets": ["pathway_region"]
}
```

- 非专项类途径（如 `regular-batch`）返回 `data_status: "unavailable"`、`regions: []`，
  并说明「本途径不设实施区域名单」。
- 名单未核验（`verified=false` 且 `counties` 为空）时必须返回 `schema_only`，
  不得输出「可报考 / 不可报考」的确定结论。
- 途径不存在返回 `1001`。

### GET `/api/pathways/region-check?province=河南&county=固始县`
Auth: no；判定该县（区）是否属于国家专项 / 高校专项的实施区域。参数 `province`、`county` 均必填。
`data` 含 `in_region`（boolean）、`region_name`（string 或 null）、`citations`。

### POST `/api/pathways/eligibility-check`
Auth: optional（游客可用）；**26 类升学途径的资格自检**，是本作品的差异化能力。

```json
{"province":"河南","score":620,"subject_type":"物理类"}
```
响应 `data` 含 `eligible`、`pending`、`ineligible`、`profile`、`citations`。

> 与 8.4 节 `/api/eligibility/check` 的区别：本接口回答「我能不能走这条通道」
> （途径维度，含专项、强基、公费师范等 26 类）；8.4 回答「这个志愿单位会不会
> 被退档 / 报不了」（志愿单位维度，四道闸门串行）。两者输入输出不同，**不可互相替代**。

## 4. 问答

### GET `/api/qa?q=620分能报哪些专业`
Auth: optional；`data` 含 `answer`、`confidence`（0~1）、`confidence_level`、`citations`。

### POST `/api/qa/ask`
Auth: optional；请求：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | 是 | 用户问题，1~500 字 |
| `session_id` | string | 否 | 多轮会话标识，最多 64 字 |
| `province` | string | 否 | 限定省份 |
| `pathway_id` | string | 否 | 限定升学途径 id（字符串 slug） |

响应 `data`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `qa_log_id` | number | 问答留痕 ID，写入 `qa_log` 表 |
| `session_id` | string/null | 回显会话标识 |
| `answer` | string | 回答正文 |
| `confidence` | number | **0~1**（契约口径） |
| `confidence_level` | `high`/`medium`/`low` | 同一判定的三档结果，供徽标直接使用。**禁止**前端另设阈值自算 |
| `citations` | array | 来源；无来源不得给出事实结论 |
| `needs_review` | boolean | 低置信 / 涉分数线时置真，自动入审核队列 |
| `degraded` | boolean | 生成失败降级为检索片段摘要时为真 |
| `elapsed_ms` | number | 本次问答耗时 |

无可核验片段时 SHALL 返回低置信 + `needs_review`，不得输出无依据事实结论。

### GET `/api/qa/history?session_id=&page=&page_size=`
Auth: yes；返回分页 `{ items, total, page, page_size }`，最近在前。
`items[]` 含 `qa_log_id`、`session_id`、`question`、`answer`、`confidence`（三档字符串）、
`citations`、`needs_review`、`degraded`、`created_at`。

## 5. 志愿方案

### POST `/api/plans`
Auth: yes；**方案生成的唯一入口**。
（v1.1 曾同时在 6.1 节定义 `POST /api/plan/generate`，属重复定义，v1.2 已删除；
前端 `api.generatePlan` 已改指向本接口。）

请求：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `profile` | object | 是 | 考生档案 |
| `strategy` | string | 是 | `冲` / `稳` / `保` |
| `priority` | string | 否 | `院校优先` / `专业优先` / `城市优先` |
| `preferred_majors` | string[] | 否 | 偏好专业 |
| `preferred_cities` | string[] | 否 | 偏好城市 |
| `accept_adjustment` | boolean | 否 | 是否服从专业调剂 |
| `limit` | number | 否 | 方案志愿总数（1~96） |
| `batch_line` | number/null | 否 | 批次控制线，未提供时不判定贴近批次线风险 |

未提供的偏好字段沿用档案 `preferences` 中已保存的值。

响应 `data` 字段（共 13 个）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `items` | array | 是 | 志愿项，每项含 `school_id`、`name`、`tier`、`risk_level` 与来源三要素 |
| `risk_notes` | string[] | 是 | 风险提示（人类可读文本） |
| `citations` | array | 是 | 依据来源 |
| `strategy` | string | 否 | 回显所用档位策略（`冲`/`稳`/`保`） |
| `priority` | string | 否 | 回显所用排序倾向 |
| `tiers` | object | 否 | **各档实际数量**，形如 `{"冲":2,"稳":4,"保":3}`；志愿条目本身在 `items[]`，按 `item.tier` 分组 |
| `quota` | object | 否 | 各档目标配额（与 `tiers` 对照可看出候选是否充足） |
| `shortage` | array | 否 | 某档候选不足的如实记录，不硬凑 |
| `excluded` | array | 否 | 被排除的院校或专业及原因 |
| `risks` | array | 否 | 方案级风险，结构同 6.1 节 `risks[]` |
| `summary` | string | 否 | 方案摘要 |
| `data_status` | string | 否 | 数据完备度（演示数据须显式标注） |
| `disclaimer` | string | 否 | 免责声明 |

## 6. 院校检索

### GET `/api/schools?keyword=郑州&province=河南&page=1&page_size=20`
Auth: no；**返回分页包** `{ items, total, page, page_size }`，每项含 `school_id`、`name`、
`province`、`city`、`level`、`type`、`ownership`、`is_985`、`is_211`、`dual_class`、`citations`。
可选过滤：`level`（本科/专科）、`type`（院校类型）、`ownership`（公办/民办）、
`is_985` / `is_211`（`true` 仅该校层次、`false` 仅非该校层次、不传不限制）、
`dual_class`（层次标记精确匹配，如 `双一流`）。

> 院校层次（`is_985` / `is_211` / `dual_class`）自 v1.5 起可用：取值来源为教育部
> 985 / 211 / 双一流 公开名单，落库口径见 `data/scripts/backfill_school_tiers.py`。
> 未标注层次的院校如实返回 `false` / `""`，**不推断**为普通院校。

> ⚠️ **破坏性变更**：v1.1 及其之前本接口返回**数组**，v1.2 起返回分页包（产品书 6.0.3 要求）。
> 前端取数处需从 `data` 改为 `data.items`。

### 6.1 其余接口一览（与后端路由一一对应）

本节所有接口要求 `Auth` 一栏所述权限，响应一律 `{code,message,data,trace_id}`；
列表类接口返回分页包时已注明。

| 接口 | Auth | 说明 |
|---|---|---|
| `POST /api/recommend` | no | **冲稳保推荐**，游客可用，不落库。请求同 5 节 `POST /api/plans`，但 `profile` 可省略：允许**扁平写法** `{province, score, subject_type, strategy, ...}`；两者混用时显式值优先。`strategy` 取 `school`/`major`/`city` 时按排序倾向解释（等价于 `priority` 的 `院校优先`/`专业优先`/`城市优先`），此时档位回退为 `稳`。响应 `data` 同 5 节。**候选数据源**：优先取库内真实录取分（`school_major_score` × `school`，普通本科批、科类精确匹配、按院校最低录取分分档）；库内无匹配数据时回落演示数据，`data_status` 记 `available` / `schema_only`，并附 `candidate_source`（`db` / `demo` / `injected`）与 `data_note` 说明。 |
| `POST /api/plan/risk-check` | yes | **方案风险体检**。请求 `{ profile: Profile, items: PlanItem[] }`；`items` 为空时返回空 `risks`。**不重新生成方案**，只对给定条目体检，与 5 节复用同一套规则。响应 `data: { risks: Risk[] }`。 |
| `GET /api/scores/segment?province=&year=&subject_type=&score=&rank=` | no | **一分一段**。`score` 与 `rank` **至少提供一个**，二者都缺返回 `1001`。响应 `data` 含 `score`、`cumulative_rank`、`same_score_count`、`citations`、`data_status`。数据未导入时返回 `schema_only` 且数值为 `null`（不得编造位次）；该省/年/科类无对应版本时返回 `unavailable`。 |
| `GET /api/schools/{school_id}` | no | 院校详情 + `citations`；不存在返回 `1001`。 |
| `GET /api/schools/{school_id}/profile` | no | 院校画像（学费 / 师资 / 校区）。该校暂无画像时返回结构完整的空态（`available=false`），而非报错。 |
| `GET /api/schools/{school_id}/life?category=` | no | 生活信息（宿舍/食堂/交通/校园环境），逐条带来源与可靠性标注。 |
| `POST /api/schools/compare` | no | 院校并排对比。请求 `{ school_ids: number[] }`，**最多 5 所**，按传入顺序返回。 |
| `GET /api/majors?category=&keyword=&page=&page_size=` | no | 专业检索，返回分页包。 |
| `GET /api/majors/{major_id}` | no | 专业详情；暂无来源的字段在 `data_status` 中说明。 |
| `GET /api/user/favorites?target_type=` | yes | 收藏列表。`items[]` 含 `favorite_id`、`target_type`（`school`/`major`）、`target_id`、`target_name`、`created_at`。 |
| `POST /api/user/favorites` | yes | 新增收藏。请求 `{ target_type, target_id }`；**幂等**：同一（用户, 类型, 对象）已存在时返回既有记录。`target_type` 非法返回 `1001`。 |
| `DELETE /api/user/favorites?target_type=&target_id=` | yes | 取消收藏；未收藏时同样返回成功（幂等）。 |
| `GET/POST /api/user/plans`；`GET/PUT/DELETE /api/user/plans/{plan_id}` | yes | 方案保存 / 命名 / 编辑 / 删除（产品书 6.1.7）。访问他人方案返回 `1003`；方案不存在返回 `1001`。 |

**Risk 结构**（5 节 `risks[]` 与 `POST /api/plan/risk-check` 共用）：
每项含 `code`（规则代码）、`type`（同 `code`）、`target`（受影响档位，方案级为 `plan`）、
`level`（`high`/`medium`/`low`）、`title`、`detail`、`evidence`、`remedy`、
`citation`（**必须**有来源三要素）。

**管理端**：`GET/POST/PUT/DELETE /api/admin/*`（Auth: admin）覆盖登录、语料、索引、审核、
途径与规则维护、统计与操作留痕，沿用统一响应包、分页结构与权限错误码
（缺令牌 `1002`、持 C 端令牌 `1003`）。规则维护接口的字段级约定见第 8.8 节。

## 7. 服务健康

### GET `/api/health`
Auth: no；`data` 为 `{"status":"ok"}`。

## 8. 报考约束（契约 v1）

本节是普通本科批报考约束的接口基线，供前后端及数据库并行开发。首期批次范围为河南、江西普通本科批；接口和数据模型保留按省份、年份、批次扩展的能力，提前批不要求本轮提供规则数据。接口统一响应仍使用 `{ code, message, data, trace_id }`。

### 8.1 统一语义

- 数据状态 `data_status ∈ available | partial | schema_only | unavailable`：`available` 表示当前接口所需规则齐全且有正式来源；`partial` 表示只有部分规则可用；`schema_only` 表示结构已就绪但规则尚未导入；`unavailable` 表示没有匹配的数据版本。
- 只有 `available` 规则可产生肯定性资格结论。规则缺失或不完整时，校验接口返回错误 `3001`，`data` 说明缺失数据集；禁止回退为“通过”。纯 Mock 仅供界面演示，必须以 `data_status: "schema_only"` 和演示来源标注，不得冒充真实规则。
- `blockers` 是硬性不符合；`warnings` 是可报但有风险/不宜/超预算；`unknowns` 是资料或规则不足以判断。`eligible` 为 `true`（无 blocker 且无 unknown）、`false`（至少一个 blocker）、`null`（无 blocker 但存在 unknown）。警告不改变 `eligible`。
- 每条 blocker / warning 必须带 `citation`，字段为 `source_name`、`source_url`、`year`。unknown 可以带关联来源；若未知来自缺失数据，使用 `data_status` / `missing_rule_sets` 表达，不伪造引用。
- 字段名以本 API 契约为准。档案预算字段沿用已有 `tuition_budget`（元/年）；引擎内部可映射为 `fee_ceiling`，API 与数据库不得同时存两份同义值。
- **可空档案项统一用 `null` 表示未提供**；不得把未填体检、预算或选科信息当作“正常”。服务端读取时必须把历史上的哨兵字符串（`""` / `"未填"` / `"未知"`）归一为 `null` 后再出接口。身体资料按最小必要原则采集，不要求身份证号或体检报告原件。
- 本节接口 JSON 只定义字段形状。示例中的学校、专业、学费、志愿数量及来源 URL 均不得直接作为正式规则种子或真实结论。

### 8.2 Profile 增量字段

`GET /api/user/profile` 和 `PUT /api/user/profile` 扩展以下字段。PUT 仍为增量更新：未传字段保持原值，显式传 `null` 清空该项。响应的 `data` 为完整 Profile，并附 `completeness: { percent: number, missing: string[] }`。

| 字段 | 类型 | 校验/说明 |
|---|---|---|
| `exam_type` | `普通\|艺术\|体育\|null` | 首期普通本科规则只接受普通类；其他类型返回对应规则未覆盖状态，不得套用普通类规则 |
| `first_subject` | `物理\|历史\|null` | 首选科目 |
| `second_subjects` | `string[]\|null` | 再选科目；元素使用项目统一科目字典 |
| `rank` | `integer\|null` | 省内位次，正整数 |
| `color_vision` | `正常\|色弱\|色盲\|不能识别红黄绿蓝紫任一色\|null` | 可跳过 |
| `vision_left`, `vision_right` | `number\|null` | 裸眼视力，小数记录法，如 4.6 |
| `height` | `number\|null` | 厘米 |
| `weight` | `number\|null` | 千克 |
| `hepatitis_b` | `boolean\|null` | 乙肝表面抗原携带情况；可跳过 |
| `hearing`, `smell`, `stutter` | `正常\|异常\|null` | 身体条件记录；`null` 表示未填，**不使用**字符串“未填” |
| `tuition_budget` | `number\|null` | 元/年，非负 |
| `batch_preference` | `string[]\|null` | 首期可填“本科批”；供后续批次扩展 |
| `accept_adjustment` | `boolean\|null` | 档案默认偏好；实际志愿项仍以志愿单位自身值为准 |

> **实现口径**：判定引擎对 `null` / `""` / `"未填"` / `"未知"` **一视同仁**视为未填，
> 一律进 `unknowns`，绝不默认放行；差异只在**出接口时必须归一为 `null`**。

### 8.3 `GET /api/provinces/{code}/rules?year=&batch=`

Auth: no。`code` 为两位省级行政区划代码（河南 `41`、江西 `36`）；`year` 必填；`batch` 必填，首期值为 `本科批`。

成功响应 `data`：

```json
{
  "province_code": "41",
  "province": "河南",
  "year": 2026,
  "batch": "本科批",
  "batch_code": "undergraduate_regular",
  "exam_type": "普通",
  "data_status": "available",
  "rule": {
    "mode": "group",
    "volunteer_count": 48,
    "majors_per_group": 6,
    "has_adjust": true,
    "admit_method": "parallel",
    "ratio": "1:1",
    "tie_rule": "以当年官方规则为准",
    "mutex_groups": [],
    "collect_count": null
  },
  "sources": [{"source_name":"官方文件名称","source_url":"https://example.gov.cn/rule","year":2026}],
  "missing_rule_sets": []
}
```

`rule` 在 `schema_only` / `unavailable` 时为 `null`；`partial` 时仅返回已核实字段，缺项列入 `missing_rule_sets`。字段枚举：`mode ∈ group | major_school | school_major`；`admit_method ∈ parallel | single`。无对应版本时仍返回 200，`data_status: "unavailable"`，不返回虚构模板。请求缺少 year/batch 或格式错误返回 `1001`。

> `batch` 是**展示名**，`batch_code` 是**机器键**。规则表与导入以 `batch_code` 作唯一键，
> 避免同一批次因各省叫法不同（如 `普通本科批` / `本科批次`）被当成不同批次。

**`batch_code` 取值与别名对照（v1.3 新增；后端 `app/models/constants.py` 与数据侧
`data/dictionaries/province-exam-rule.json` 已统一，契约对齐二者）**：

| `batch_code`（机器键，唯一键成分） | 首期 `batch`（展示名） | 归一前的展示别名（导入时映射到左侧，**不得当成不同批次**） |
|---|---|---|
| `undergraduate_regular` | `本科批` | `普通本科批`（河南）、`本科批次`（江西） |
| `undergraduate_early` | `提前批` | `普通本科提前批` |
| `undergraduate_art_sport` | `艺术类/体育类本科批次` | — |
| `vocational_regular` | `高职（专科）批` | `高职（专科）批次` |

> **`batch_code` 不含省份前缀。** 省份维度由 `province_exam_rule` 主键里的 `province_code`
> 承载；若把省份编进 `batch_code`（如 `HE-UG` / `JX-UG`），同一次「本科批」会被拆成两个键，
> 与本节「归一后不得再区分」的要求相悖。契约 v1.2 曾用 `HE-UG` 作示例，v1.3 已更正。
> 未登记的展示名不得静默落入默认值，须由数据侧补登后重新导入。

### 8.4 `POST /api/eligibility/check`

Auth: no（游客可用）。一次最多校验 100 个志愿单位；空 `items` 合法并返回 `summary.total=0`。请求只能携带本次校验所需档案字段；登录用户调用此游客接口时，不自动信任或读取用户档案。

```json
{
  "profile": {
    "province": "河南", "exam_type": "普通", "first_subject": "物理",
    "second_subjects": ["化学", "生物"], "score": 620, "rank": 18000,
    "color_vision": null, "vision_left": null, "vision_right": null,
    "height": null, "weight": null, "hepatitis_b": null,
    "hearing": null, "smell": null, "stutter": null,
    "household_type": "农村", "home_county": null, "home_county_code": null,
    "school_years": null, "tuition_budget": 15000
  },
  "year": 2026,
  "items": [
    {"unit_id":"henan-ug-001","batch":"本科批","school_id":"school-1","group_code":"01","major_ids":["major-1","major-2"]}
  ],
  "pathway_id": null
}
```

Profile 中 `province`、`exam_type`、`year` 及每个 item 的 `batch` 必须足以唯一定位规则；其余可空字段缺失时进入 `unknowns`。每个 item 的 `unit_id` 在请求内唯一，`major_ids` 是该志愿单位实际填报的专业集合；专业组结构和数量以省份模板校验。`pathway_id` 为字符串 slug 或 `null`。

成功响应 `data`：

```json
{
  "data_status": "available",
  "items": [{
    "unit_id": "henan-ug-001",
    "eligible": null,
    "blockers": [],
    "warnings": [{
      "type":"physical", "level":"not_suitable", "detail":"该专业存在不宜就读提示",
      "major_ids":["major-1"], "major_names":["示例专业"],
      "citation":{"source_name":"官方文件名称","source_url":"https://example.gov.cn/rule","year":2026}
    }],
    "unknowns": [{"type":"physical","level":"unknown","detail":"未填写体检结论，相关身体限制待核验","fields":["color_vision"]}],
    "citations": [{"source_name":"官方文件名称","source_url":"https://example.gov.cn/rule","year":2026}]
  }],
  "summary": {"total":1,"blocked":0,"warned":1,"unknown":1}
}
```

命中项 `type ∈ province_rule | subject | physical | fee | score | language | gender | batch | pathway`；`level ∈ reject | not_suitable | unknown`。`blockers` 只能包含 `reject`，`warnings` 可包含 `not_suitable` 或 `soft`（如超预算），`unknowns` 使用 `unknown`。`summary` 统计“至少含该类命中”的志愿单位数，单位可同时计入 warned 和 unknown；`eligible` 按 8.1 规则计算。每条 hit 的 `major_ids` / `major_names` 可选，用于指出受影响专业。

若定位到的规则集是 `schema_only`、`unavailable` 或缺少执行该批校验所必需的规则，返回错误 `3001`：

```json
{"code":3001,"message":"报考规则数据尚未就绪，无法完成校验","data":{"data_status":"schema_only","missing_rule_sets":["province_exam_rule","subject_requirement"]},"trace_id":"trace"}
```

错误 `1001`：字段非法、重复 unit_id、超过 100 项、年份/批次缺失或结构不合法。不得将 `3001` 转换为成功响应或清空规则后继续判为 eligible。

### 8.5 `POST /api/user/eligibility/check`

Auth: yes。请求/响应语义与 8.4 相同，`profile` 可省略；省略时使用当前用户档案快照。若同时传 `profile`，仅允许覆盖校验所需字段，不写回档案。响应额外包含 `updated_profile` 的既有兼容说明仅在规则引擎确实更新 `has_national_special`、`has_local_special`、`has_college_special` 或 `accept_adjustment` 时返回；普通本科通用校验默认不修改这些档案字段。

### 8.6 `GET /api/majors/{id}/requirements?province=&year=`

Auth: no。`province` 使用省级行政区划代码，`year` 必填。返回该省该年度专业要求，不能跨省/跨年复用其他版本。

```json
{
  "major_id":"major-1", "province_code":"41", "year":2026,
  "data_status":"available",
  "subject_req":{"first":"物理","secondary":["化学"],"logic":"all"},
  "physical_restrictions":[{
    "condition":"color_vision", "threshold":{"operator":"in","value":["色弱","色盲"]},
    "level":"reject", "detail":"具体限制说明",
    "citation":{"source_name":"官方文件名称","source_url":"https://example.gov.cn/rule","year":2026}
  }],
  "tuition":{"amount":58000,"currency":"CNY","period":"year","ownership":"中外合作","note":"按官方收费标准"},
  "enrollment_notes":{"single_subject_req":null,"language_req":null,"gender_req":null,"interview_required":null},
  "sources":[{"source_name":"官方文件名称","source_url":"https://example.gov.cn/rule","year":2026}],
  "missing_rule_sets":[]
}
```

`subject_req.first ∈ 物理 | 历史 | null`，`secondary` 为科目字典值数组，`logic ∈ all | any`；`all` 表示必须满足数组中所有再选科目，`any` 表示满足其中至少一项。未知要求用 `null`，不得以空数组冒充“无限制”；明确不限时 `subject_req` 返回 `{ "first": null, "secondary": [], "logic": "all" }` 且来源必须覆盖该判断。`physical_restrictions[].level ∈ reject | not_suitable`，阈值操作符 `threshold.operator ∈ in | eq | lt | lte | gt | gte | between`，`threshold.value` 为对应标量、数组或区间端点。`tuition.amount` 为元/年；收费未知时 `tuition: null` 并将规则集列入 `missing_rule_sets`。`enrollment_notes.single_subject_req` 为 `{ subject, minimum_score } | null`，`language_req` 为 `{ allowed_languages: string[] } | null`，`gender_req ∈ male | female | any | null`，后三个 boolean 字段 `interview_required`、`political_review_required`、`physical_test_required` 取 `boolean | null`（null 表示未知）。专业不存在返回 `1001`（资源不存在沿用现有错误处理约定，由后端统一映射）。

### 8.7 规则数据表与导入约定

数据库可以调整物理命名，但必须保留以下逻辑字段、唯一性和版本语义。所有规则表都要求 `year`、`source_name`、`source_url`；来源缺失或无法识别省份/批次/适用专业的记录不得作为可用规则。

| 逻辑表 | 唯一键/必备字段 | 约束 |
|---|---|---|
| `province_exam_rule` | `(province_code, year, batch_code, exam_type)`；`mode`、`volunteer_count`、`majors_per_group`、`has_adjust`、`admit_method`、`ratio`、`tie_rule`、`mutex_groups`、`collect_count`、来源三要素 | `mode`、`admit_method` 限定为接口枚举；历史年份并存，不覆盖旧版本 |
| `subject_requirement` | `(province_code, year, school_id, target_type, target_id)`；`first`、`secondary[]`、`logic`、来源三要素 | `target_type ∈ group/major`，`target_id` 必填；每条明确适用到专业或专业组；`logic ∈ all/any`；明确不限与数据缺失必须可区分 |
| `physical_restriction` | `(province_code, year, condition, threshold_operator, threshold_value, target_type, target_id)`；`level`、`detail`、来源三要素 | `level ∈ reject/not_suitable`；`target_type ∈ major/major_category`，`target_id` 为稳定代码，避免只靠展示名匹配 |
| `admission_requirement` | `(province_code, year, school_id, major_id, requirement_type)`；`requirement_value`、`level`、`detail`、来源三要素 | 承载单科、语种、性别、面试/政审/体测等章程要求；用于支撑接口 `enrollment_notes`，避免将其误塞入身体限制表 |
| `major_tuition` | `(province_code, year, school_id, major_id)`；`amount`、`currency`、`period`、`ownership`、`note`、来源三要素 | 学费按具体学校/专业/年份存储；不得仅以办学性质估算值冒充正式数据 |
| `rule_dataset_status` | `(province_code, year, batch_code, exam_type, dataset)`；`status`、`updated_at`、`note` | `dataset` 对应以上规则集；`status ∈ available/partial/schema_only/unavailable`。API 根据该表和规则覆盖率判定状态，区分“明确不限”与“尚未导入” |

**批次与考试类型的收敛（数据工程必读）**：

- 规则表的唯一键使用 `batch_code`，`batch` 仅作展示。当前各省叫法差异
  （河南 `普通本科批`、江西 `本科批次`）经 `batch_code` 归一后不得再区分。
- 数据源列名 `category_group` 对应契约字段 `exam_type`，导入时**必须改名**。
- 数据工程内部的 `data_status` 中间状态（`verified` / `pending` 等）**不得直接出接口**，
  须按上表映射为契约的四个取值；数据文件自身的 README/校验脚本口径也应同步，
  避免出现第三套词表。

建议将以上约束记录视作有版本的事实数据，保留导入批次与数据状态（`available/partial/schema_only/unavailable`）。管理端录入和导入校验必须检查年份、地域、适用对象、枚举和来源；记录被停用或替换时保留审计信息。首期只需准备河南、江西普通本科批数据结构和导入通道，实际规则由数据成员核实后导入；前后端可先用 schema-only Mock 开发。

数据库实现建议：以 UUID 主键（或项目已冻结的主键规范）和 `created_at/updated_at` 审计列为默认；每条规则保留来源三要素。给规则查询键建立复合索引：省份/年份/批次代码/考试类型、专业/专业组目标键；所有规则表通过逻辑键保证同一年度同一适用范围不产生重复有效记录。`secondary`、`mutex_groups`、阈值结构等可用 PostgreSQL `JSONB` 或数组实现，但序列化后的 API 结构必须一致。若采用软删除/有效标志，唯一性约束必须只约束有效记录。

### 8.8 管理端规则维护接口

以下接口全部要求 admin 角色，沿用 `{code,message,data,trace_id}`。GET 返回分页 `{ items, total, page, page_size }`，支持 `province_code`、`year`、`batch`、`data_status` 过滤。POST 创建规则，PUT `/.../{rule_id}` 更新规则；请求字段与 8.7 对应逻辑表一致，并包含 `source_name`、`source_url`、`year`。字段缺失、年份/枚举非法、来源不完整返回 `4001`；逻辑键重复返回 `1001`，更新不存在的 ID 使用项目统一资源不存在错误。`available` 状态必须由导入覆盖率/完整性校验得出，不允许管理端手工强制设为 available。

| 接口 | 用途 |
|---|---|
| `GET/POST /api/admin/province-rules`；`PUT /api/admin/province-rules/{rule_id}` | 维护省份 × 年份 × 批次 × 考试类型模板 |
| `GET/POST /api/admin/subject-requirements`；`PUT /api/admin/subject-requirements/{rule_id}` | 维护专业/专业组的选科要求 |
| `GET/POST /api/admin/physical-restrictions`；`PUT /api/admin/physical-restrictions/{rule_id}` | 维护身体条件限制；`level` 仅 `reject/not_suitable` |
| `GET/POST /api/admin/admission-requirements`；`PUT /api/admin/admission-requirements/{rule_id}` | 维护单科、语种、性别、面试/政审/体测等要求 |
| `GET/POST /api/admin/major-tuition`；`PUT /api/admin/major-tuition/{rule_id}` | 维护按省份、年份、院校专业维度的学费 |
| `GET/PUT /api/admin/rule-dataset-status` | 查询/更新省份、年份、批次、考试类型下各规则集的 `data_status` 与说明 |
| `POST /api/admin/rule-datasets/import` | 数据成员批量导入 JSON 规则项，单次最多 500 条；全批事务写入，任一项校验失败整批回滚，响应返回 `dataset`、`created`、`updated`、`rejected`、`errors[]` |

批量导入请求形状：`{ "dataset": "subject_requirement", "province_code": "41", "year": 2026, "batch_code": "undergraduate_regular", "exam_type": "普通", "items": [...] }`。`dataset` 只能取 `province_exam_rule | subject_requirement | physical_restriction | admission_requirement | major_tuition`；每个 item 应符合该逻辑表字段。成功导入后，后端重新计算/更新对应 `rule_dataset_status`；只有必要规则覆盖完整且来源有效时，状态才能置为 `available`。导入接口不接受来源缺失记录，不接受演示来源 `example.invalid`。

### 8.9 后端与数据库交付检查点

- 后端：实现以上三个公开接口、登录用户批量接口、Profile 增量保存；Pydantic 请求/响应类型与本文件字段一致；引擎为纯函数，服务层读取版本化规则后调用。
- 数据库：实现规则逻辑表及迁移、唯一约束/索引、来源校验和按省份/年份/批次查询；为未来提前批保留模型能力，但本轮无需编造或导入提前批规则。
- 未有真实数据时，规则查询明确返回 `schema_only` / `unavailable`；校验请求返回 `3001` 并列出缺失表/规则集。演示 Mock 与数据库真实数据必须通过同一 DTO 验证。
- 接口验收至少覆盖：河南/江西本科批版本读取、数据未导入返回 `3001`、每种档案缺项进入 unknown、选科不符 blocker、身体 reject blocker、not_suitable warning、超预算 warning、同一单位可返回多条命中、100/101 项边界、重复请求幂等、每个硬/软命中均含来源。

### 8.10 基础事实表的补充列（0008 / 0009）

第 7.1 节的基础事实表在实际装载中确认需要补充以下列。**均为新增可空/带默认值列，不改变任何既有接口的响应形状**；
本章之前契约未收录这些字段，现补录使「契约 = 实际表结构」。

#### 8.10.1 录取分的身份列（0009，重点）

| 列 | 类型 | 说明 |
|---|---|---|
| `group_code` | string(32) | **院校专业组代码**。河南为「院校专业组」志愿模式，志愿表按专业组渲染；第 5 节 `PlanItem` 的 `group_code` 即取自此。 |
| `major_code` | string(32) | **专业代号**（招生计划口径，**不是**国标专业代码）。将来据此回挂 `major_id`。 |
| `major_name` | string(200) | 专业名称 |
| `exam_system` | string(16) | 考试制度：`文理科` / `3+1+2`。**跨制度不得比较** —— 老高考与新高考的分数、位次不可混算。 |

**为什么需要（超出第 7 章）**：数据侧产物首期 `major_id` 整列留空，**一行录取分的真实身份是「专业组 + 专业」**。
官方样本已有实例 —— `data/samples/school_major_score.json` 中
「河南 / 2025 / 本科批 / 物理类 / 560 分 / 101279 位次」**出现两行，仅专业不同**
（`major_code` = `14` 公共管理类 / `12` 国际商务）。缺 `major_code` / `major_name`
则既**无法区分行**，也**定义不了幂等键**。

**导入键（幂等 upsert）**：`(school_id, province, year, batch, subject_type, group_code, major_code)`，
对应索引 `ix_school_major_score_identity`。

#### 8.10.2 其余补充列

| 表 | 列 | 说明 |
|---|---|---|
| `school` | `is_985` / `is_211` / `dual_class` | **院校层次**，冲稳保推荐与家长决策的核心维度；两套数据源中只有一套带该信息，合并在装载层完成 |
| `major` | `intro` | **专业简介**正文，产品端「专业介绍」直接可用 |
| `score_segment` | `batch` | 一分一段**批次**。老高考一条连续曲线被批次线切段（本科一批 / 二批 / 专科批），累计值连续，**合并会丢批次线信息**，故必须按 `batch` 保留 |
| `score_segment` | `same_score_count` | **同分人数**（累计位次之外的口径），可空 |

#### 8.10.3 两条红线（数据工程与装载层必守）

1. **`school_id` 是位置耦合的** —— 数据侧 `school_id` 等于其院校库的 **1-based 行序号**（实测 `1367/1367` 成立；
   北京大学 51 / 清华大学 55 / 安徽财经大学 243）。一旦有院校行被跳过，后续 id **整体位移**，
   **11.6 万行会静默错挂院校**，且无任何约束能发现。故：
   ① 院校装载**必须显式采用数据侧的 id 作主键**，不得自行重新编号；
   ② 消费侧 `school_id` 必须存在，缺失时**跳过并上报**（如 `unknown_school_id`），
   **绝不降级为 `NULL`** —— 那等于把「错位」伪装成「客观缺失」。
2. **可空 ≠ 可推断** —— `school_id` / `major_id` 允许为 `null`（数据侧实测 1,983 行无院校、2,200 行无专业），
   但**只允许是数据侧明确标空的真实未匹配**；装载层不得自行推断补全，未匹配行必须原样入库并登记原因。
   契约红线仍是「**宁可缺，不可猜**」。

## 附录 A. 前后端路径对照表

联调前逐行核对本表；`frontend/src/api/index.ts` 中出现的每个 `/api` 路径都应在本表中。
后端已由 `backend/test_alignment.py` 自动断言该一致性。

| 前端方法 | 路径 | Auth | 后端模块 |
|---|---|---|---|
| `register` | `POST /api/auth/register` | no | `api/v1/auth.py` |
| `login` | `POST /api/auth/login` | no | `api/v1/auth.py` |
| `login(admin)` | `POST /api/admin/login` | no | `api/v1/admin/auth.py` |
| `logout` | `POST /api/auth/logout` | yes | `api/v1/auth.py` |
| `me` | `GET /api/auth/me` | yes | `api/v1/auth.py` |
| `getProfile` / `updateProfile` | `GET/PUT /api/user/profile` | yes | `api/v1/profile.py` |
| `deleteAccount` | `DELETE /api/user` | yes | `api/v1/auth.py` |
| `pathways` | `GET /api/pathways` | no | `api/v1/pathways.py` |
| `pathwayDetail` | `GET /api/pathways/{id}` | no | `api/v1/pathways.py` |
| `regions` | `GET /api/pathways/{id}/regions` | no | `api/v1/pathways.py` |
| `regionCheck` | `GET /api/pathways/region-check` | no | `api/v1/pathways.py` |
| `eligibility(auth=false)` | `POST /api/eligibility/check` | no | `api/v1/eligibility.py` |
| `eligibility(auth=true)` | `POST /api/user/eligibility/check` | yes | `api/v1/eligibility.py` |
| `ask` | `POST /api/qa/ask` | optional | `api/v1/qa.py` |
| `qaHistory` | `GET /api/qa/history` | yes | `api/v1/qa.py` |
| `generatePlan` | `POST /api/plans` | yes | `api/v1/plans.py` |
| `recommend` | `POST /api/recommend` | no | `api/v1/recommend.py` |
| `riskCheck` | `POST /api/plan/risk-check` | yes | `api/v1/recommend.py` |
| `scoreSegment` | `GET /api/scores/segment` | no | `api/v1/scores.py` |
| `plans` / `plan` / `savePlan` / `updatePlan` / `deletePlan` | `/api/user/plans[/{id}]` | yes | `api/v1/user_plans.py` |
| `schools` / `school` / `schoolProfile` / `schoolLife` / `compareSchools` | `/api/schools[...]` | no | `api/v1/schools.py` |
| `majors` / `major` | `/api/majors[/{id}]` | no | `api/v1/majors.py` |
| `favorites` / `addFavorite` / `removeFavorite` | `/api/user/favorites` | yes | `api/v1/favorites.py` |
| `adminDocs` / `uploadDoc` / `deleteDoc` | `/api/admin/docs[/{id}]` | admin | `api/v1/admin/docs.py` |
| `rebuildIndex` / `indexTask` | `/api/admin/index/...` | admin | `api/v1/admin/index.py` |
| `adminPathways` / `savePathway` / `rules` / `saveRule` / `pathwayRegions` | `/api/admin/pathways*`、`/api/admin/pathway-rules*`、`/api/admin/pathway-regions` | admin | `api/v1/admin/pathways.py` |
| `reviewTasks` / `reviewTask` / `reviewAction` | `/api/admin/review/tasks[/{id}]` | admin | `api/v1/admin/review.py` |
| `adminStats` | `GET /api/admin/stats` | admin | `api/v1/admin/stats.py` |
| — | `/api/provinces/{code}/rules` | no | `api/v1/eligibility.py`（8.3） |
| — | `/api/majors/{id}/requirements` | no | `api/v1/eligibility.py`（8.6） |
| — | `/api/admin/{province-rules,subject-requirements,physical-restrictions}` | admin | `api/v1/admin/rules.py`（8.8） |

> 未实现但已被产品书提及、**明确留待后续能力建设**的接口（当前不在契约内，前端不得调用）：
> `GET /api/schools/{id}/life` 之外的生活信息细分类别扩展、
> 以及第 6.1 节中暂未列出的任何管理端接口。新增接口须先按「变更流程」登记。

## 统一 Mock

前端设置 `VITE_USE_MOCK=true` 时使用 `frontend/src/mocks/index.ts`，无需启动后端即可开发。
真实接口联调时改为 `false`。

> **注意**：Mock 的字段形状必须与本契约一致。历史上 Mock 形状与真实接口不一致，
> 导致「开着 Mock 一切正常、关掉 Mock 成片报错」。修改接口时**必须同时**更新
> 本文件、`frontend/src/types/api.d.ts` 与 `frontend/src/mocks/index.ts`。

## 变更流程

破坏性字段变更必须同时更新本文件、Mock 和 OpenAPI，并在 PR 描述中填写接口变更项；先通知受影响模块负责人，再合并到 `develop`。

追加式（向后兼容）变更同样必须同步本文件、`frontend/src/types/api.d.ts` 与 `frontend/src/mocks/index.ts`，保持三方字段一致。本文件由队长维护，队员如需变更请先在群里说明。

> v1.2 登记的破坏性变更：`GET /api/schools` 由数组改为分页包；
> `data_status` 词表统一为四值；`pathway_id` 统一为字符串 slug；
> 档案三态字段出接口一律为 `null`。上述变更须由前端与数据工程在各自分支同步。

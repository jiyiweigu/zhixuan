# 智选志愿 API Contract v1

## 统一约定

- Base URL: `http://localhost:8000`
- 所有路径使用 `/api` 前缀，字段使用 `snake_case`。
- 响应包：`{ code, message, data, trace_id }`。
- 错误码：`1001` 参数错误，`1002` 未登录，`1003` 无权限，`1006` 用户名重复，`1008` 登录失败次数超过阈值（限流），`1500` 未捕获的服务端异常。
- 鉴权：标注 `Auth: yes` 的接口必须带 `Authorization: Bearer <access_token>`（登录/注册响应中的 `access_token`）；缺失或不合法返回 `1002`。
- 事实数据必须带 `source_name`、`source_url`、`year`。问答必须返回 `citations` 与 0~1 的 `confidence`；缺引用的结论不得展示。

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

`data` 字段（共 12 个）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `province` | string | 是 | 报考省份 |
| `score` | number | 是 | 高考总分 |
| `subject_type` | string | 是 | 科类，如 `物理类` |
| `household_type` | string | 否 | 户籍类型，`农村` / `城镇`；用于专项计划资格判定 |
| `household_county` | string | 否 | 户籍所在县（区） |
| `enrollment_county` | string | 否 | 学籍所在县（区） |
| `household_years` | number | 否 | 户籍年限 |
| `enrollment_years` | number | 否 | 当地学籍年限 |
| `parent_household_local` | boolean | 否 | 法定监护人户籍是否在当地 |
| `special_marks` | string[] | 否 | 特殊身份标记（如少数民族、烈士子女） |
| `preferences` | object | 否 | 偏好设置，见下 |
| `updated_at` | string | 否 | 最后更新时间，ISO 8601 |

`preferences` 子字段：`priority`（`城市优先` / `专业优先`）、`preferred_majors`（string[]）、`preferred_cities`（string[]）、`accept_adjustment`（boolean）。

第 4~12 项为**追加字段**，可缺省；缺省时相关判定按「未提供」处理，不得默认成立。

### PUT `/api/user/profile`
Auth: yes；请求字段同上表，响应为档案对象。

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
Auth: no；单条升学途径详情，`data` 为路径对象（字段同列表项）。

### GET `/api/pathways/region-check?province=河南&county=固始县`
Auth: no；判定该县（区）是否属于国家专项 / 高校专项的实施区域。参数 `province`、`county` 均必填。
`data` 含 `in_region`（boolean）、`region_name`（string 或 null）、`citations`。
> 本接口由 `feature/fei` 实现，`data` 的字段级结构待该分支合并后逐项复核。

### POST `/api/pathways/eligibility-check`
Auth: no（游客可用）；请求：
```json
{"province":"河南","score":620,"subject_type":"物理类"}
```
响应 `data` 含 `eligible`、`pending`、`ineligible`、`profile`、`citations`。

## 4. 问答

### GET `/api/qa?q=620分能报哪些专业`
Auth: optional；`data` 含 `answer`、`confidence`、`citations`。

## 5. 志愿方案

### POST `/api/plans`
Auth: yes；请求：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `profile` | object | 是 | 考生档案 |
| `strategy` | string | 是 | `冲` / `稳` / `保` |
| `priority` | string | 否 | `城市优先` / `专业优先` |
| `preferred_majors` | string[] | 否 | 偏好专业 |
| `preferred_cities` | string[] | 否 | 偏好城市 |
| `accept_adjustment` | boolean | 否 | 是否服从专业调剂 |

未提供的偏好字段沿用档案 `preferences` 中已保存的值。

响应 `data` 字段（共 13 个）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `items` | array | 是 | 志愿项，每项含 `school_id`、`name`、`tier`、`risk_level` 与来源三要素 |
| `risk_notes` | string[] | 是 | 风险提示 |
| `citations` | array | 是 | 依据来源 |
| `strategy` | string | 否 | 回显所用策略 |
| `priority` | string | 否 | 回显所用倾向 |
| `tiers` | object | 否 | 按 `冲` / `稳` / `保` 分组的志愿项 |
| `quota` | string[] | 否 | 名额相关信息 |
| `shortage` | string[] | 否 | 缺额 / 断档提示 |
| `excluded` | string[] | 否 | 被排除的院校或专业及原因 |
| `risks` | string[] | 否 | 方案级风险 |
| `summary` | string | 否 | 方案摘要 |
| `data_status` | string | 否 | 数据完备度（演示数据须显式标注） |
| `disclaimer` | string | 否 | 免责声明 |

## 6. 院校检索

### GET `/api/schools?keyword=郑州&province=河南`
Auth: no；`data` 为院校数组，每项含 `school_id`、`name`、`province`、`citations`。

## 7. 服务健康

### GET `/api/health`
Auth: no；`data` 为 `{"status":"ok"}`。

## 统一 Mock

前端设置 `VITE_USE_MOCK=true` 时使用 `frontend/src/mocks/index.ts`，无需启动后端即可开发。真实接口联调时改为 `false`。

## 变更流程

破坏性字段变更必须同时更新本文件、Mock 和 OpenAPI，并在 PR 描述中填写接口变更项；先通知受影响模块负责人，再合并到 `develop`。

追加式（向后兼容）变更同样必须同步本文件、`frontend/src/types/api.d.ts` 与 `frontend/src/mocks/index.ts`，保持三方字段一致。本文件由队长维护，队员如需变更请先在群里说明。

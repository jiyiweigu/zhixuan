# 智选志愿 API Contract v1

## 统一约定

- Base URL: `http://localhost:8000`
- 所有路径使用 `/api` 前缀，字段使用 `snake_case`。
- 响应包：`{ code, message, data, trace_id }`。
- 错误码：`1001` 参数错误，`1002` 未登录，`1003` 无权限，`1006` 用户名重复。
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

## 2. 考生档案

### GET `/api/user/profile`
Auth: yes
```json
{"code":0,"message":"success","data":{"province":"河南","score":620,"subject_type":"物理类"},"trace_id":"trace"}
```

### PUT `/api/user/profile`
Auth: yes；请求字段：`province`、`score`、`subject_type`，响应为档案对象。

## 3. 路径

### GET `/api/pathways`
Auth: no；返回路径数组，每项含 `id`、`name`、`status` 和来源三要素。

### POST `/api/pathways/eligibility-check`
Auth: no（游客可用）；请求：
```json
{"province":"河南","score":620,"subject_type":"物理类"}
```
响应 `data` 含 `eligible`、`pending`、`profile`、`citations`。

## 4. 问答

### GET `/api/qa?q=620分能报哪些专业`
Auth: optional；`data` 含 `answer`、`confidence`、`citations`。

## 5. 志愿方案

### POST `/api/plans`
Auth: yes；请求：`profile`、`strategy`（`冲`/`稳`/`保`）；响应含 `items`、`risk_notes`、`citations`。

## 6. 院校检索

### GET `/api/schools?keyword=郑州&province=河南`
Auth: no；`data` 为院校数组，每项含 `school_id`、`name`、`province`、`citations`。

## 统一 Mock

前端设置 `VITE_USE_MOCK=true` 时使用 `frontend/src/api/mock.ts`，无需启动后端即可开发。真实接口联调时改为 `false`。

## 变更流程

破坏性字段变更必须同时更新本文件、Mock 和 OpenAPI，并在 PR 描述中填写接口变更项；先通知受影响模块负责人，再合并到 `develop`。

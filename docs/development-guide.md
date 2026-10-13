# 成员开发指南

## 一、每天开工

```bash
# 1. 先同步集成分支（在你的 feature/* 分支上执行）
git checkout feature/fei      # 各自换成 xu / fei / zhang / yuan
git pull origin develop

# 2. 开发……提交……推送
git add -A
git commit -m "feat(qa): 问答接口返回 citations 与 confidence"
git push origin feature/fei

# 3. 到 GitHub 提 PR：base = develop
```

顺序不能颠倒：**必须先 `checkout` 到自己的分支，再 `pull`**。停在 `develop` 上 pull 只会更新本地副本，自己分支什么也没同步。

## 二、先读这三份

1. [API 契约](api-contract.md) —— 前后端字段的唯一依据，**以它为准**，不要以 Mock 为准。
2. [Mock 说明](mock-data.md) —— 六模块 × success / empty / error 三档数据。
3. [任务分工](team-tasks.md) —— 分支模型与共享文件约定。

## 三、前端启动

```bash
cd frontend
npm install
cp .env.example .env          # Windows: copy .env.example .env
npm run dev                   # http://localhost:5173
```

默认 `VITE_USE_MOCK=true`，走本地 Mock，**不需要启动后端**。要与真实后端联调时改成 `false`。

页面请求统一走 `src/api/`，字段用 `snake_case`；登录成功后调用 `setToken(access_token)` 把令牌存进 localStorage，`src/api` 会自动带上 `Authorization` 头。事实性结论必须带引用。

## 四、后端启动

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate                  # Windows；macOS / Linux 用 source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                    # 填写 DATABASE_URL、JWT_SECRET 等，勿提交
alembic upgrade head                    # 建表 / 迁移到最新版本
uvicorn app.main:app --reload           # http://localhost:8000/docs
```

数据库需先装 PostgreSQL 16 并启用扩展：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

新增数据库迁移：

```bash
alembic revision --autogenerate -m "描述本次变更"
alembic upgrade head
```

## 五、自查与验收

```bash
python tests/mock_contract_smoke.py           # 契约冒烟（仓库根目录执行）
cd frontend && npm run typecheck && npm run build
```

前端类型检查必须为 0 错误；后端接口改动的，请同步更新 `docs/api-contract.md`、`frontend/src/types/api.d.ts`、`frontend/src/mocks/index.ts` 三处再提交 PR（这三份属共享文件，需先找队长）。

## 六、新增第三方依赖

按规范「新增第三方依赖前先申报」。已在用的后端依赖及许可：

| 依赖 | 用途 | 许可 |
|---|---|---|
| `fastapi` | Web 框架 | MIT |
| `uvicorn[standard]` | ASGI 服务器 | BSD-3-Clause |
| `pydantic` | 数据校验 | MIT |
| `sqlalchemy` | ORM | MIT |
| `alembic` | 数据库迁移 | MIT |
| `pyjwt` | 令牌签发与校验 | MIT |
| `httpx` | 异步 HTTP 客户端 | BSD-3-Clause |

上表为宽松许可，无传染风险。新增其他依赖前请在站会说明用途与许可。

## 七、数据与合规

真实数据由后续爬虫与人工核验提供，**当前不得提交密钥、隐私或未经审核的政策数据**。所有事实性数据必须带 `source_name`、`source_url`、`year` 三要素。

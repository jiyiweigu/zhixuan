# 协作规范（CONTRIBUTING）

> 完整说明见《开发产品书_智选志愿.md》第 10 章。本文件是仓库入口版，团队 5 人必读。

## 一、账号与权限（主账号 = 队长）

- 仓库由**队长账号**创建，其余 4 人由队长在 `Settings → Collaborators` 邀请，权限给 **Write**。
- **团队内部不使用 Fork 流程**，全员在同一仓库上用分支协作；外部贡献者请 Fork 后提 PR。
- `main` 已开启分支保护：必须有 PR 且至少 1 人批准才能合并。
- 本仓库为**公开的开源仓库（[MIT 许可](./LICENSE)）**——因此**严禁提交任何密钥、账号密码、个人隐私信息或未公开的第三方数据**。

## 二、第一次使用（每人一次）

```bash
git config --global user.name "你的姓名拼音"
git config --global user.email "你的邮箱"
git config --global core.autocrlf true
```

认证二选一：HTTPS + Personal Access Token（权限勾 `Contents: Read and write`），或配置 SSH Key。

```bash
git clone https://github.com/<队长用户名>/zhixuan.git
cd zhixuan
```

## 三、分支模型

| 分支 | 用途 | 谁能推 |
|---|---|---|
| `main` | 稳定可演示版本，合并后打 tag | 仅队长（经 PR） |
| `develop` | 集成分支 | 经 PR 合并 |
| `feature/<模块>-<姓名拼音>` | 个人开发分支 | 本人 |

**已建好的成员分支**（都已从 `develop` 拉出，直接切换过去开发即可，不用自己建）：

| 分支 | 对应角色 |
|---|---|
| `feature/backend-xu` | ② 后端 |
| `feature/data-fei` | ③ 数据工程 |
| `feature/rag-zhang` | ④ 算法 / RAG |
| `feature/admin-yuan` | ⑤ 管理端前端 + 测试 + 材料 |

例：`feature/backend-xu`、`fix/plan-rank-zhang`。**禁止**中文、空格、`test`、`dev`、`master`。

## 四、每日六步流程

```bash
# 1 同步集成分支
git checkout develop
git pull origin develop
# 2 切到自己的分支（已由队长建好；若没有则 git checkout -b feature/<模块>-<姓名拼音>）
git checkout feature/backend-xu
git merge develop
# 3 开发 + 小步提交
git status
git add 具体文件
git commit -m "feat(qa): 问答接口返回 citations 与 confidence"
# 4 推送
git push -u origin feature/backend-xu
# 5 到 GitHub 提 PR（base=develop）
# 6 审查通过后 Squash merge，并删除自己的分支
```

## 五、提交信息格式

`type(scope): 中文描述`，type ∈ `feat` `fix` `docs` `refactor` `test` `chore` `perf`

```
feat(eligibility): 实现资格规则引擎与规则依据输出
fix(qa): 修正低置信答案未自动入审核队列的问题
docs(readme): 补充本地启动步骤与默认账号
```

禁止：`update`、`修改`、`111`、`最终版`。

## 六、Pull Request 要求

- 标题：`[模块] 做了什么`
- 描述按 `.github/pull_request_template.md` 填写
- PR 前先 `git pull origin develop` 并本地跑通
- 不把多个不相关功能塞进一个 PR；单 PR 建议 ≤500 行
- 合并方式统一 **Squash and merge**

## 七、绝对不能做

1. 直接往 `main` / `develop` 推代码
2. `git push -f`、`git reset --hard`
3. 提交 `.env`、API Key、密码
4. 提交 `node_modules/`、`.venv/`、大体积数据集
5. `git add .` 一把梭
6. 删除别人的分支
7. 改别人负责的模块文件不打招呼
8. 在功能 PR 里顺手全文件格式化
9. 把 AI 给的命令不经确认直接执行
10. 用中文或空格命名分支

## 八、卡住了怎么办

不要自己乱试。把下面这段填好发给队长或 AI：

```
【GitHub 求助】
1. 我的分支：
2. 我想做的事：
3. git status 输出：
4. 报错信息：
5. 团队规范：main=稳定、develop=集成、我的分支 feature/<模块>-<姓名拼音>；
   提交格式 type(scope): 中文描述；禁止 push -f 和 reset --hard。

请给逐条可复制命令，并说明每步作用与风险；涉及可能丢代码的操作请明确警告。
```

## 九、数据与合规约定（涉及作品评分，务必遵守）

- 所有事实性数据必须带 `source_name`、`source_url`、`year` 三要素，缺一不得入库、不得展示。
- 事实性结论**没有引用就不展示**。
- 禁止在代码、日志、提交中出现真实用户隐私数据。
- 新增第三方依赖前先在站会提出并说明许可。

## 十、目录与命名

- Python 文件/变量 `snake_case`；Vue 组件 `PascalCase`；接口字段统一 `snake_case`。
- 新增页面放 `frontend/src/views/user/` 或 `frontend/src/views/admin/`。
- 新增后端接口放 `backend/app/api/v1/` 对应模块文件，业务逻辑写进 `app/services/`。

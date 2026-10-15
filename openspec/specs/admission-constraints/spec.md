# admission-constraints Specification

## Purpose
TBD - created by archiving change add-admission-constraints. Update Purpose after archive.
## Requirements
### Requirement: 分步维护约束档案

系统 SHALL 在现有考生档案中支持约束校验所需的考试类型、首选/再选科目、分数与位次、体检字段、学费预算及批次偏好。前端 SHALL 将基础报考信息与可选的体检/预算信息分步呈现；档案接口 SHALL 支持增量保存并返回完整度及未填写字段。可选信息允许暂不填写，`null` SHALL 表示未知，不得转换为“正常”或“无限制”。档案字段按 `docs/api-contract.md` 第 8.2 节。

#### Scenario: 用户分步保存档案
- **WHEN** 已登录用户先保存省份、考试类型、选科和分数，再补填体检或预算并提交
- **THEN** 服务端 SHALL 保留未在第二次请求中提交的已有字段，更新本次字段，并返回完整档案与完成度

#### Scenario: 体检信息暂不填写
- **WHEN** 用户跳过体检字段并执行后续校验
- **THEN** 系统 SHALL 保留字段为未知并在受影响单位返回待核验提示，不得将其视为身体条件正常

#### Scenario: 用户修改档案
- **WHEN** 用户更改选科、体检或预算字段
- **THEN** 前端 SHALL 清除基于旧档案缓存的单位校验结果，避免展示过期结论

### Requirement: 按地域与年度查询规则状态

系统 SHALL 按省份代码、年份、批次和考试类型查询对应志愿模板，并按省份、年份查询专业的选科、身体、学费及招生章程要求。规则 SHALL 按版本隔离并附来源名称、来源链接和年份。系统 SHALL 区分 `available`、`partial`、`schema_only`、`unavailable`；未导入规则不得解释为“不限”。首期支持河南、江西普通本科批的模板与数据接入路径，且 SHALL 为后续批次保留相同版本化模型。

#### Scenario: 查询已就绪的本科批模板
- **WHEN** 客户端以省份代码、年份和本科批请求规则，且该规则集已核验完整
- **THEN** 系统 SHALL 返回对应省份、年份、考试类型的模板、数据状态与来源

#### Scenario: 真实规则尚未导入
- **WHEN** 客户端请求一个已建表但尚无正式规则数据的省份/年份/批次
- **THEN** 查询接口 SHALL 返回 `schema_only` 或 `unavailable`、空规则和缺失规则集说明，不得返回虚构模板作为正式数据

#### Scenario: 查询专业的版本化要求
- **WHEN** 客户端请求一个专业在特定省份和年份的要求
- **THEN** 系统 SHALL 返回该版本的选科要求、身体限制、收费和章程要求及来源，不得使用其他省份或年份的规则替代

### Requirement: 确定性四闸门规则引擎

后端 SHALL 通过不访问数据库、网络或大模型的纯函数，对服务层传入的完整规则快照执行省份模板、选科、身体条件和学费四类校验。引擎 SHALL 区分 `reject` 硬拦截、`not_suitable`/预算风险软提示和资料缺项待核验；相同档案与规则输入 SHALL 产生相同结果。所有硬拦截与软提示 SHALL 提供对应来源依据。

#### Scenario: 选科不匹配
- **WHEN** 考生首选或再选科目不满足某专业/专业组的明确要求
- **THEN** 校验 SHALL 返回类型为选科的 blocker、缺失科目说明和规则引用

#### Scenario: 身体条件不予录取
- **WHEN** 已知考生体检条件命中来源明确且级别为 `reject` 的专业限制
- **THEN** 校验 SHALL 将该命中加入 blockers，并标明受影响的专业和引用依据

#### Scenario: 身体条件不宜就读或超出预算
- **WHEN** 已知考生条件命中 `not_suitable` 规则，或专业年学费高于其预算上限
- **THEN** 校验 SHALL 将该命中作为 warning 保留在结果中，并附规则来源或收费来源

#### Scenario: 档案信息不足
- **WHEN** 当前规则可用但一个或多个相关档案字段为 `null`
- **THEN** 校验 SHALL 将该字段影响加入 unknowns，并将单位状态标为待核验

#### Scenario: 规则数据缺失或不完整
- **WHEN** 执行校验所需的任一规则集状态为 `schema_only`、`unavailable`，或其覆盖不足以支持该请求
- **THEN** 服务端 SHALL 返回错误码 `3001` 和缺失规则集，不得生成通过结论

### Requirement: 批量校验志愿单位

系统 SHALL 提供游客和已登录用户可用的批量志愿单位校验接口，最多接受 100 个单位；每个单位 SHALL 返回 blocker、warning、unknown、引用和 eligible 状态。`eligible` 仅在无 blocker 且无 unknown 时为 `true`，有 blocker 时为 `false`，无 blocker 但有 unknown 时为 `null`。服务端 SHALL 返回分档数量摘要；空列表 SHALL 返回总数为零的成功结果。接口字段以 API Contract v1.1 第 8.4–8.5 节为准。

#### Scenario: 扫描一张普通本科志愿表
- **WHEN** 客户端提交不超过 100 个普通本科批志愿单位及同一考生档案
- **THEN** 系统 SHALL 对每个单位返回三档命中、引用与摘要计数

#### Scenario: 同一单位命中多类约束
- **WHEN** 一个单位同时不满足选科并命中身体条件硬限制
- **THEN** 系统 SHALL 返回两条独立 blocker，不得互相覆盖或仅返回第一条

#### Scenario: 请求数量越界或单位重复
- **WHEN** 请求超过 100 个单位、包含重复 `unit_id` 或结构字段不合法
- **THEN** 服务端 SHALL 返回 `1001`，且不得部分处理后返回成功

#### Scenario: 空批次扫描
- **WHEN** 客户端提交空 `items` 数组
- **THEN** 服务端 SHALL 返回成功且 `summary.total` 为 0

#### Scenario: 游客执行校验
- **WHEN** 未登录用户提交自带档案和志愿单位
- **THEN** 服务端 SHALL 在不读取或持久化其个人账户档案的情况下执行同一规则校验

### Requirement: 展示可解释且非静默的校验结果

用户端 SHALL 在 `/profile` 展示档案分步录入、完成度及未填项影响；在 `/eligibility` 展示路径/专业适配结果；在 `/plan` 提供整张方案的风险体检；在专业/院校详情展示可用要求及来源。前端 SHALL 以 blocker、warning、unknown 三类呈现服务端结果，不得自行重算或改判；主动搜索和方案检查中的拦截项 SHALL 可见并可查看原因，不得静默隐藏。规则数据未就绪时 SHALL 明确显示无法核验状态，不得显示为“通过”。新增界面 SHALL 延续现有 Editorial 编辑杂志风视觉规范和移动端响应式行为。

#### Scenario: 查看被拦截的志愿项
- **WHEN** 风险体检发现一个或多个硬拦截志愿单位
- **THEN** 用户 SHALL 能打开被拦截项列表并查看原因、关联专业和规则引用

#### Scenario: 查看待核验项
- **WHEN** 志愿单位因未填体检或预算信息存在 unknown
- **THEN** 页面 SHALL 标记“待核验”、说明影响并引导用户补充档案，不得用绿色通过状态呈现

#### Scenario: 规则数据未就绪
- **WHEN** 接口返回 `3001` 或规则查询返回 `schema_only` / `unavailable`
- **THEN** 页面 SHALL 展示规则数据待导入/无法判断状态，并保留重试或查看缺失数据说明的入口

#### Scenario: 查看专业要求
- **WHEN** 用户打开专业详情且接口返回了版本化规则
- **THEN** 页面 SHALL 展示选科、身体、学费及招生要求，并在事实性结论旁呈现来源与年份

### Requirement: 规则数据维护与导入

系统 SHALL 保存省份志愿模板、选科要求、身体限制、章程要求、专业学费和规则数据集状态，并保留省份、年份、批次、考试类型及来源。管理端 SHALL 支持有权限的规则查询、创建、更新和数据集状态查询；批量导入 SHALL 限制条数、验证来源与逻辑键、在事务内执行并返回导入统计。规则集 SHALL 只能在覆盖完整性和来源校验通过后变为 `available`。首期 SHALL 提供河南、江西普通本科批的数据结构和导入通路，但不要求伪造或预置正式规则。

#### Scenario: 保存缺少来源的规则
- **WHEN** 管理员提交缺少来源名称、URL、年份或适用地域的规则
- **THEN** 服务端 SHALL 返回 `4001` 并拒绝保存

#### Scenario: 导入批次含有非法记录
- **WHEN** 批量导入中任意记录违反字段、来源、版本或唯一性约束
- **THEN** 系统 SHALL 回滚整批写入并返回可定位到记录的错误信息

#### Scenario: 同一年份规则并存
- **WHEN** 数据库已有一个年度的省份规则，又导入另一个年度
- **THEN** 系统 SHALL 保留两个版本并允许分别查询，不得覆盖旧年度记录

#### Scenario: 未核实规则不能标记可用
- **WHEN** 规则覆盖不完整或来源验证未通过
- **THEN** 系统 SHALL 保持 `partial`、`schema_only` 或 `unavailable` 状态，并拒绝将其标成 `available`

### Requirement: 管理员权限与操作留痕

管理端规则维护和导入接口 SHALL 要求 admin 权限。用户端 SHALL 不得调用写入规则或更新规则数据状态的操作；前端隐藏入口不得替代服务端授权。

#### Scenario: 普通用户尝试修改规则
- **WHEN** 未授权用户请求新增、更新或导入规则
- **THEN** 服务端 SHALL 拒绝请求并返回统一的未登录或无权限错误

#### Scenario: 管理员更新规则
- **WHEN** 授权管理员修改有效规则
- **THEN** 系统 SHALL 更新版本记录并保留操作者、时间和变更前后数据的审计信息

### Requirement: 约束校验质量门槛

系统 SHALL 为纯函数引擎、API、数据状态和前端关键状态提供自动化验证。验收 SHALL 覆盖普通本科模板、选科逻辑、身体限制级别、预算、未知字段、数据未就绪、溯源、批量边界与幂等；真实数据尚未导入时，测试 SHALL 使用明确标注的测试夹具，不能将其当作生产规则。

#### Scenario: 核验阻断、警告和待核验分类
- **WHEN** 测试分别构造选科/体检不符合、合格不宜/超预算和未填档案场景
- **THEN** 自动化测试 SHALL 验证结果分别进入 blockers、warnings 和 unknowns，且 eligible 状态符合定义

#### Scenario: 核验所有已输出结论的来源
- **WHEN** 引擎返回一个 blocker 或 warning
- **THEN** 测试 SHALL 验证该命中包含有效来源名称、URL 和年份

#### Scenario: 核验不完整数据保护
- **WHEN** 测试移除校验所需的数据集或将其标为未就绪
- **THEN** 服务 SHALL 返回 `3001`，且任何单位都不得被判定为 eligible

#### Scenario: 核验确定性与数量边界
- **WHEN** 相同输入重复校验，或分别提交 100 与 101 个单位
- **THEN** 相同输入 SHALL 产生相同 JSON 结果；100 项可处理，101 项 SHALL 返回 `1001`


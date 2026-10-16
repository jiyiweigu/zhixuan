## Why

T6 的目标是把现有四闸门引擎、规则库、管理端导入通道与 eligibility API 串成可验收链路。代码和数据骨架已经存在，但具体目标的规则定位、覆盖状态和 2026 真实规则可用范围必须以本地当前版本重新核实；否则“接口能跑”容易被误解为河南、江西所有专业规则均已齐备。

## What Changes

- 补齐现有选科规则按专业组/专业目标精确查询与覆盖判定，确保缺规则、未解析规则和非选科考试制度都按已冻结契约表达，不静默放行。
- 补齐体检规则对目标专业/专业类的适用范围过滤、档案缺项表达和规则依据回传；未知规则语义不得被当作不命中。
- 复核并修正服务层规则集状态与 `3001` 错误边界，使必需规则集缺失时不产生任何 `eligible: true`，可选规则集状态遵循 API v1.5。
- 用当前 importer 通道验证 2026 江西省份模板规则及河南/江西现有 2026 规则数据；仅依据已登记的一手来源修正数据，不补造选科或体检规则。
- 建立基于当前字典真实行的对账报告：按省份/年份统计 `ok`、`missing`、`unparsed`，并量化 2026 请求中会触发 `3001` 的目标覆盖率；报告明确分母、目标键和计算口径。
- 为纯函数、服务/API、导入与回归路径补充验收测试，保持既有 DTO、错误码、四闸门顺序和前后端契约不变。

## Capabilities

### New Capabilities

无。此变更补齐现有报考约束能力，不新增 API 能力域。

### Modified Capabilities

- `admission-constraints`: 明确目标级规则覆盖/缺失判定、2026 年规则版本隔离和 `3001` 的全请求失败语义。

## Impact

- 后端：`backend/app/engine/constraints.py`、`backend/app/services/constraints.py`、约束 API/数据模型及 importer；仅在核实发现必要时调整实现。
- 数据：`data/dictionaries/subject-requirement.json`、`data/dictionaries/physical-restriction.json`、`data/dictionaries/province-exam-rule.json` 与 `data/sources/source-table.json`；使用现有来源和导入通道，不将 2024/2025 选科数据套用于 2026。
- 测试与交付：`backend/test_constraints.py`、`backend/test_engine.py`、相关 importer 测试及一份覆盖率/缺失规则对账产物。
- 接口：继续遵循 `docs/api-contract.md` v1.5 §8.1–8.8；预期不改变请求/响应 DTO。若实施中证明必须改契约，先单独说明并更新 OpenSpec delta 后再实现。
- 工作区：以当前本地分支为事实来源；实施范围限于 T6 必需文件，不切分支、不提交或推送，不覆盖其他未提交工作。

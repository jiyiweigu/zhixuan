# -*- coding: utf-8 -*-
"""Mock 契约冒烟检查（结构级，不做字面量硬匹配）。

用途：确认前端 mock 与类型层仍满足三条底线，可在任意一次改动后快速自检。
  1. 溯源三要素 source_name / source_url / year 在 mock 与类型中都存在；
  2. 统一响应包 code / message / data / trace_id 在类型中定义；
  3. api 层引用的每个 fixtures.<模块> 都在 mock 中真实定义（防"引用了不存在的 mock"）。

运行：在仓库根目录执行  python tests/mock_contract_smoke.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOCK = (ROOT / 'frontend/src/mocks/index.ts').read_text(encoding='utf-8')
API = (ROOT / 'frontend/src/api/index.ts').read_text(encoding='utf-8')
TYPES = (ROOT / 'frontend/src/types/api.d.ts').read_text(encoding='utf-8')

# 1. 溯源三要素
for token in ('source_name', 'source_url', 'year'):
    assert token in MOCK, f'[FAIL] mock 缺少溯源字段：{token}'
    assert token in TYPES, f'[FAIL] 类型缺少溯源字段：{token}'

# 2. 统一响应包
for token in ('code', 'message', 'data', 'trace_id'):
    assert token in TYPES, f'[FAIL] 类型缺少统一响应包字段：{token}'

# 3. api 层引用的 fixtures 模块必须在 mock 中定义
used = set(re.findall(r'fixtures\.([A-Za-z_]\w*)', API))
assert used, '[FAIL] api 层未引用任何 fixtures，mock 开关可能已失效'

defined_block = MOCK.split('export const fixtures', 1)[-1]
defined = set(re.findall(r'(?:^|[{,\s])([A-Za-z_]\w*)\s*:', defined_block, re.M))
missing = sorted(used - defined)
assert not missing, f'[FAIL] mock 缺少 api 层引用的模块：{missing}'

# 4. 报考约束三档输出（接入中，暂作提示而非断言，避免阻塞日常自检）
constraint_ready = all(t in TYPES or t in MOCK for t in ('blockers', 'warnings', 'unknowns'))

print(f'mock contract smoke check passed（fixtures 模块 {len(defined)} 个，api 引用 {len(used)} 个）')
if constraint_ready:
    print('[ok] 约束三档字段 blockers / warnings / unknowns 已就位')
else:
    print('[todo] 约束三档字段尚未落地 —— 见 docs/执行计划_报考约束接入.md 第 2 节（P0 契约三件套）')

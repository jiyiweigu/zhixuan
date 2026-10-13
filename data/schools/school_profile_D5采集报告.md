# D5 · `school.type` / `website` / `intro` 采集报告

- 生成日期：2026-10-13 ｜ 责任人：徐（③ 数据工程）
- 目标表：`school` ｜ 目标字段：`type`、`website`、`intro`
- 产物：`data/schools/schools_merged.json`（主产物）+ 三个补丁文件（见文末）

---

## 一、结论（覆盖率）

| 字段 | 补前 | 补后 | 覆盖率 | 来源等级 |
|---|---|---|---|---|
| `city` | 31 | 31 | **100%** | 官方（教育部名单）+ 官方补录 |
| `ownership` | 31 | 31 | **100%** | 官方（教育部名单）+ 官方补录 |
| `type` | 1367 全空 | 289 空 | **78.9%**（1078/1367） | 软科（★非官方） |
| `website` | 1367 全空 | 391 空 | **71.4%**（976/1367） | 软科候选 + **实测校验**（官方级） |
| `intro` | 1367 全空 | 419 空 | **69.3%**（948/1367） | **官方优先**（900 条=校官网简介页）；48 条回退软科 |

分布：
- `type` 11 类：理工 331 / 综合 264 / 师范 183 / 财经 92 / 医药 90 / 农业 38 / 语言 24 / 政法 23 / 民族 14 / 体育 13 / 林业 6
- `intro` 构成：**官方（各校官网「学校简介/学校概况」页）900 条 + 软科非官方 48 条 + 空 419**

校验：`validate.py --kind school` → **1367/1367 通过、0 错误**；三个补丁文件分别 900/900、1085/1085、1084/1084 全 PASS；`merge_schools.py` 幂等（md5 稳定）。

---

## 二、修掉的核心缺陷：补丁从不落地

D2（`type`）、D5（`website`/`intro`）此前只产出**独立补丁文件**，`schools_merged.json` 里三字段**始终为 0**。
本次改造 `merge_schools.py`：加载三份补丁 → 按校名匹配 → **仅填空值**（不覆盖已有）→ 逐条写入溯源字段 `_type_src` / `_website_src` / `_intro_src`。

> ★ 主产物 `schools_merged.json` 是 ②（后端）灌数的规范输入，补丁必须合入主产物才有意义。

---

## 三、数据来源与可信度分层

| 字段 | 发现方式 | 校验方式 | 可写入主字段的条件 |
|---|---|---|---|
| `type` | 软科 BCUR 11 榜合并（`univCategory`） | 跨榜冲突 0 | 口径**待裁**（N16），当前为软科口径 |
| `website` | 软科院校详情接口 `/api/pub/v1/inst/{slug}` 的 `url` 字段 | **实测校验**：https 优先 + HTTP 200 + 页面出现校名 | **仅校验通过者写入主字段**；未通过降级 `_website_candidate` |
| `intro` | ① 各校官网「学校简介」页正文抽取（官方）；② 软科详情接口 `intro`（非官方兜底） | 中文正文 ≥120 字、页头/页脚/导航过滤、按校名截断 | 官方优先，官方缺失才用软科 |
| `city`/`ownership` | 教育部名单「主管部门」推导 + 名单外 31 所官方补录 | 1280 所交叉验证、回归冲突 0 | 见《school_ownership补缺报告.md》 |

**关键口径（合规）**：团队铁律要求事实数据带**三要素**并标注**来源等级**。因此：
- `website` 一律经**实测校验**（HTTP 200 + 校名命中）才进主字段 —— 等价于官方级；
- `intro` **官方来源优先**（900/948 = 94.9%），非官方的 48 条在 `_intro_src.official=false` 显式标注，可随时弃用；
- `type` 目前**只有软科一个口径**，属非官方，需队长拍板（N16）。

---

## 四、缺口归因（419 所无 `intro`）

| 归因 | 数量 | 说明 |
|---|---|---|
| **未进软科榜** | 289 | 军校（22）+ 中国科学院大学/中国社会科学院大学 + 部分高职/新设院校 —— 三个字段（type/website/intro）的共同缺口来源 |
| 有软科候选但**官网校验未通过** | 102 | 失败原因见下 |
| 有官网但**无独立简介页** | 28 | 抽取器不达标（宁可缺不可猜，留空） |

`website` 候选校验未通过的 102 条，失败原因分布：

| 原因 | 数量 | 说明 |
|---|---|---|
| DNS 不存在 / 域名失效 | ~35 | 软科登记的老域名已停用 |
| SSL 不兼容（`SSLV3_ALERT` / `DH_KEY_TOO_SMALL` / `UNSAFE_LEGACY_RENEGOTIATION`） | ~20 | 站点证书老旧，Python 默认 SSL 策略拒绝 |
| HTTP 412（瑞数 WAF） | ~15 | 同 `haeea.cn` 现象 |
| 超时 / 502 / 202 | ~30 | 站点本身不稳定 |

> 这 102 条**不是脚本 bug**，是站点侧客观不可达。若要补，需逐校换域名或人工核，属长尾。

---

## 五、待裁事项

| 编号 | 内容 | ③ 建议 |
|---|---|---|
| **N16** | `type` 口径：软科 11 类（理工/综合/师范…）是否为团队认定口径？是否需映射为教育部「办学类型」（大学/学院/高职）？ | 软科口径可用于前端展示；若要入 `school.type` Enum 需 ② 定枚举 |
| **N17** | `website`/`intro` 逐条溯源字段 `_website_src`/`_intro_src` 是否入表？ | 建议入表（合规留痕），但需 ② 在 `school` 加列或改存 `school_profile` |

> ★ 当前 `_type_src` / `_website_src` / `_intro_src` / `_website_candidate` 均为 **③ 侧溯源标记**，以 `_` 前缀命名，**尚未进入模型**；② 灌数时需显式忽略或落库（待定）。

---

## 六、复现命令

```bash
PY=C:/Users/lenovo/.workbuddy/binaries/python/envs/default/Scripts/python.exe

# 1) type 补丁（软科 11 榜，离线走缓存）
python data/scripts/build_school_type_supplement.py --offline

# 2) website + 软科 intro 候选（软科详情接口 + 实测校验；--offline 走详情缓存）
python data/scripts/build_school_web_intro_supplement.py --offline --workers 24 --verify-timeout 10

# 3) 官方站 intro（逐校官网「学校简介」页；--all 含已有软科简介者一并重采）
python data/scripts/build_school_official_intro.py --all --workers 24

# 4) 合入主产物（三方补丁 + city/ownership 推导 + 31 所补录）
python data/scripts/merge_schools.py

# 5) 校验
python data/scripts/validate.py data/schools/schools_merged.json --kind school
```

> 采集页面缓存位于 `data/schools/.cache_site/`（127M，已加入 `.gitignore`，不入库）。

---

## 七、产物清单

| 文件 | 说明 |
|---|---|
| `data/schools/schools_merged.json` | 主产物（1367 所，三字段已合入 + 逐条溯源） |
| `data/schools/school_type_supplement.json` | `type` 补丁（1084 条，覆盖 1078 所） |
| `data/schools/school_web_intro_supplement.json` | `website` + 软科 `intro` 补丁（1085 条） |
| `data/schools/school_official_intro_supplement.json` | 官方站 `intro` 补丁（900 条） |
| `data/scripts/build_school_type_supplement.py` | `type` 采集（含改名院校原名匹配） |
| `data/scripts/build_school_web_intro_supplement.py` | `website` 候选 + 实测校验 |
| `data/scripts/build_school_official_intro.py` | 官方站简介抽取 |

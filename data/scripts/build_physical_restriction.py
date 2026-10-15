# -*- coding: utf-8 -*-
"""
体检专业限制映射表生成器（闸门③弹药 · T5）
==========================================
产出：data/dictionaries/physical-restriction.json（入库）

权威依据（每条规则 basis 可逐条溯源）：
  1. 教育部、卫生部、中国残联《普通高等学校招生体检工作指导意见》
     （教学〔2003〕3号）——主依据，三个清单天然对应三个分级：
       第一部分 → blocker（学校可以不予录取，普适性、不映射专业类）
       第二部分 → blocker（学校有关专业可不予录取，专业类映射主体）
       第三部分 → warning（不宜就读，知情提示；原文注明"学校不得以此为依据
                  拒绝录取达到相关要求的考生"）
  2. 教学厅〔2010〕2号——取消乙型肝炎表面抗原携带者限报条款与乙肝项目检测
     （保留转氨酶 ALT）；原 2003 二.6 条进入 superseded 区（不参与导入/判档）。
  3. 《军队选拔军官和文职人员体检标准》通用标准（军队院校招生执行）——
     身高/体重指数/视力（军校系单独组织军检，属专项资格）。
  4. 《公安院校公安专业招生体检标准》（公安部，2025 年执行版）——
     身高/体重指数/视力/色觉/听力（警校系单独组织警检，属专项资格）。

数据口径（红线：宁可缺、不可猜）：
  - 分级铁律：blocker = 原文「可不予录取」；warning = 原文「不宜就读」。
    **绝不把 warning 错标成 blocker**。
  - `major_categories`（类级）与 `major_names`（点名专业）**分开保留**：
    原文点名「X类各专业」→ 类级；原文枚举具体专业 → 专业级（不上卷到类，
    避免过度拦截，如「飞行技术」上卷「交通运输类」会误伤「交通工程」）。
  - 点名专业→类/代码 由专业库（938 专业 / 93 专业类）自动解析，旧名走
    显式别名（侦察学→侦查学 等），解析不到的 fail loudly，不静默丢弃。
  - `engine_ready` 标记该条当前档案/引擎能否求值（供 T6 过滤）：
    需引擎扩展（4.5 视力线、BMI 区间、性别维度、矫正度数）者为 false。

专业库来源：`data/majors/majors.json`（仓库内基线，**离线可复跑依赖**）；仓库外
  `桌面/智选志愿_数据整合/merged/major.json` 若存在则并入扩大覆盖面，缺失不报错。

用法：python build_physical_restriction.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # data/
OUT_PATH = BASE_DIR / "dictionaries" / "physical-restriction.json"
MERGE_MAJOR = Path(r"C:\Users\Administrator\Desktop\智选志愿_数据整合\merged\major.json")
CATALOG_MAJOR = BASE_DIR / "majors" / "majors.json"

SOURCE_GUIDE = "SRC-MOE-PHYSICAL-GUIDE"      # 教学〔2003〕3号
SOURCE_HEPB = "SRC-MOE-HEPB-2010"            # 教学厅〔2010〕2号
SOURCE_ARMY = "SRC-ARMY-MEDICAL-STD"         # 军队选拔军官和文职人员体检标准
SOURCE_POLICE = "SRC-MPS-POLICE-MEDICAL"     # 公安院校公安专业招生体检标准

BASIS_GUIDE = "《普通高等学校招生体检工作指导意见》（教学〔2003〕3号）"
BASIS_ARMY = "《军队选拔军官和文职人员体检标准》（军队院校招生执行）"
BASIS_POLICE = "《公安院校公安专业招生体检标准》（公安部，2025年执行版）"

# 旧名/异写 → 现行目录专业名（仅收录有确证对应的；无法确证一律不映射）
MAJOR_ALIAS = {
    "侦察学": "侦查学",                       # 2003 年写法，现行名"侦查学"
    "特种能源工程与烟火技术": "特种能源技术与工程",
    "资源勘探工程": "资源勘查工程",           # 现名"资源勘查工程"（地质类）
    "博物馆学": "文物与博物馆学",
    "艺术设计": "视觉传达设计",               # 2003"艺术设计"拆分入设计学类
    "民族传统体育": "武术与民族传统体育",
}

# ── 原文名单（已逐条对照 2026 年现行版全文，不凭印象）──────────────────

# 第二部分 1：色弱不能录取 —— 类级 6 类 + 医学类各专业 + 点名专业 37 个
COLOR_WEAK_CATS = ["化学类", "化工与制药类", "药学类", "生物科学类", "公安技术类", "地质学类"]
COLOR_WEAK_MENLEI = ["医学"]
COLOR_WEAK_NAMES = [
    "生物工程", "生物医学工程", "动物医学", "动物科学", "野生动物与自然保护区管理",
    "心理学", "应用心理学", "生态学", "侦察学", "特种能源工程与烟火技术", "考古学",
    "海洋科学", "海洋技术", "轮机工程", "食品科学与工程", "轻化工程", "林产化工",
    "农学", "园艺", "植物保护", "茶学", "林学", "园林", "蚕学", "农业资源与环境",
    "水产养殖学", "海洋渔业科学与技术", "材料化学", "环境工程", "高分子材料与工程",
    "过程装备与控制工程", "学前教育", "特殊教育", "体育教育", "运动训练",
    "运动人体科学", "民族传统体育",
]

# 第二部分 2：色盲（除同轻度色觉异常外 + 17 个点名专业）
COLOR_BLIND_EXTRA_NAMES = [
    "美术学", "绘画", "艺术设计", "摄影", "动画", "博物馆学", "应用物理学",
    "天文学", "地理科学", "应用气象学", "材料物理", "矿物加工工程", "资源勘探工程",
    "冶金工程", "无机非金属材料工程", "交通运输", "油气储运工程",
]

# 第二部分 3：不能识别红黄绿蓝紫任一色（除同前两类外 + 6 类 + 计算机）
NO_DISTINCT_EXTRA_CATS = [
    "经济学类", "管理科学与工程类", "工商管理类", "公共管理类",
    "农业经济管理类", "图书情报与档案管理类", "计算机类",
]

# 第三部分 1：主要脏器手术史/病史等不宜就读（类级 + 点名专业）
ORGAN_CATS = [
    "地质类", "矿业类",                                   # 原文「地矿类」
    "水利类", "交通运输类", "能源动力类", "公安学类", "体育学类",
    "海洋科学类", "大气科学类", "水产类", "测绘类", "海洋工程类",
    "林业工程类", "兵器类",                                 # 原文「武器类」
    "林学类",                                             # 原文「森林资源类」
    "环境科学与工程类",                                   # 原文「环境科学类」
    "自然保护与环境生态类",                               # 原文「环境生态类」
    "旅游管理类", "草学类",                               # 原文「草业科学类」
]
ORGAN_NAMES = ["土木工程", "消防工程", "农业水利工程", "农学", "法医学",
               "水土保持与荒漠化防治", "动物科学"]

# 第三部分 4：屈光不正矫正4.8、度数>400
D400_NAMES = ["海洋技术", "海洋科学", "测控技术与仪器", "核工程与核技术",
              "生物医学工程", "服装设计与工程", "飞行器制造工程"]

# 第三部分 5：矫正4.8、度数>800（类级 + 点名专业）
D800_CATS = [
    "地质类", "矿业类",                                   # 原文「地矿类」
    "水利类",
    "土木类", "建筑类",                                   # 原文「土建类」
    "动物生产类", "水产类", "材料类", "能源动力类", "化工与制药类",
    "兵器类",                                             # 原文「武器类」
    "农业工程类", "林业工程类", "植物生产类",
    "林学类",                                             # 原文「森林资源类」
    "自然保护与环境生态类",                               # 原文「环境生态类」
    "心理学类",
    "环境科学与工程类", "安全科学与工程类",               # 原文「环境与安全类」
    "电子信息类",                                         # 原文「电子信息科学类」
    "地质学类", "大气科学类",
]
D800_MENLEI = ["医学"]
D800_NAMES = ["地理科学", "测绘工程", "交通工程", "交通运输", "油气储运工程",
              "船舶与海洋工程", "生物工程", "草业科学", "动物医学"]

# 第三部分 6：一眼失明另一眼矫正4.8、度数>400
BLIND_EYE_MENLEI = ["工学", "农学", "医学", "法学"]
BLIND_EYE_NAMES = ["应用物理学", "应用化学", "生物技术", "地质学", "生态学",
                   "环境科学", "海洋科学", "海洋技术", "生物科学", "应用心理学"]

# 第三部分 7：听力（类级 + 点名专业）
HEARING_CATS = ["法学类", "外国语言文学类"]               # 原文「各专业」
HEARING_MENLEI = ["医学"]
HEARING_NAMES = ["外交学", "新闻学", "侦查学", "学前教育", "音乐学", "录音艺术",
                 "土木工程", "交通运输", "动物医学", "动物科学"]

# 第三部分 8：嗅觉迟钝/口吃/步态异常等（应用范围相同）
FACE_CATS = ["教育学类", "公安学类"]
FACE_NAMES = ["外交学", "法学", "新闻学", "音乐表演", "表演"]

# 第三部分 9：斜视、嗅觉迟钝、口吃 → 医学类专业
MED9_MENLEI = ["医学"]

KEYS = ["不能识别红黄绿蓝紫任一色", "色弱", "色盲", "色觉", "裸眼视力", "乙肝",
        "身高", "体重", "听力", "嗅觉", "口吃"]


def R(rule_id, condition, group, severity, scope, *, cats=None, menlei=None,
      names=None, threshold="", basis="", source="", remark="", ready=True,
      note="", extends=None):
    if scope == "universal":
        mapping_level = "universal"
    elif scope in ("military", "police"):
        mapping_level = "institution"          # 作用于该类院校全部专业（军检/警检）
    elif (cats or menlei) and names:
        mapping_level = "class+major"
    elif cats or menlei:
        mapping_level = "class"
    else:
        mapping_level = "major"
    return {
        "rule_id": rule_id, "condition": condition, "condition_group": group,
        "severity": severity, "scope": scope,
        "mapping_level": mapping_level,
        "major_categories": list(cats or []),
        "major_menlei": list(menlei or []),
        "major_names": list(names or []),
        "threshold": threshold,
        "basis": basis, "source_id": source, "remark": remark,
        "engine_ready": ready, "engine_note": note,
        "extends": extends,
    }


def build_rules() -> list[dict]:
    r = []
    P = BASIS_GUIDE
    S = SOURCE_GUIDE

    # ── 第一部分：学校可以不予录取（普适，不映射专业类）──
    r.append(R("PR-2003-1-01", "严重心脏病、心肌病、高血压病", "心血管",
               "blocker", "universal",
               basis=f"{P} 一、1", source=S, ready=False,
               remark="先天性心脏病经手术治愈、房室间隔缺损分流量少、动脉导管未闭返流血量少"
                      "且经二级以上医院确认无需手术者除外；属体检结论/档案核查项。",
               note="档案无对应字段，属体检结论核查项。"))
    r.append(R("PR-2003-1-02", "重症支气管扩张、哮喘、恶性肿瘤、慢性肾炎、尿毒症", "呼吸/肿瘤/泌尿",
               "blocker", "universal", basis=f"{P} 一、2", source=S, ready=False,
               remark="属体检结论/档案核查项，不映射专业类。"))
    r.append(R("PR-2003-1-03", "严重的血液、内分泌及代谢系统疾病、风湿性疾病", "血液/内分泌/风湿",
               "blocker", "universal", basis=f"{P} 一、3", source=S, ready=False,
               remark="属体检结论/档案核查项，不映射专业类。"))
    r.append(R("PR-2003-1-04", "重症或难治性癫痫、严重精神病未治愈、精神活性物质滥用和依赖", "神经/精神",
               "blocker", "universal", basis=f"{P} 一、4", source=S, ready=False,
               remark="属体检结论/档案核查项，不映射专业类。"))
    r.append(R("PR-2003-1-05", "慢性肝炎且肝功能不正常", "肝功能",
               "blocker", "universal", basis=f"{P} 一、5", source=SOURCE_HEPB,
               ready=False,
               remark="肝炎病原携带者但肝功能正常者除外；『肝功能不正常』判定标准见"
                      "卫医政管便函〔2010〕76号：ALT 超过参考值上限 2 倍以上（含）应 B 超复查。"
                      "教学厅〔2010〕2号取消乙肝项目检测，保留转氨酶（ALT）检测。"))
    r.append(R("PR-2003-1-06", "结核病（除已硬结稳定等三种例外情形外）", "结核",
               "blocker", "universal", basis=f"{P} 一、6", source=S, ready=False,
               remark="例外情形：①原发型/浸润性肺结核已硬结稳定、结核型胸膜炎已治愈或遗有"
                      "胸膜肥厚；②肺外结核/血行播散型肺结核治愈一年以上未复发且专科检查无变化；"
                      "③淋巴腺结核临床治愈无症状。属体检结论/档案核查项。"))

    # ── 第二部分：学校有关专业可不予录取（blocker，专业映射主体）──
    r.append(R("PR-2003-2-01", "色弱", "色觉", "blocker", "national",
               cats=COLOR_WEAK_CATS, menlei=COLOR_WEAK_MENLEI, names=COLOR_WEAK_NAMES,
               basis=f"{P} 二、1", source=S,
               remark="原文：轻度色觉异常（俗称色弱）不能录取【类级】化学类、化工与制药类、"
                      "药学类、生物科学类、公安技术类、地质学类各专业，医学类各专业；【点名专业】"
                      "见 major_names；专科专业清单见原文（本表按本科专业目录口径）。"))
    r.append(R("PR-2003-2-02", "色盲", "色觉", "blocker", "national",
               cats=COLOR_WEAK_CATS, menlei=COLOR_WEAK_MENLEI,
               names=COLOR_WEAK_NAMES + COLOR_BLIND_EXTRA_NAMES,
               basis=f"{P} 二、2", source=S, extends="PR-2003-2-01",
               remark="原文：色觉异常Ⅱ度（俗称色盲）不能录取的专业，除同轻度色觉异常外，"
                      "还包括 major_names 中标注（色盲新增）的 17 个点名专业。"))
    r.append(R("PR-2003-2-03", "不能识别红黄绿蓝紫任一色", "色觉", "blocker", "national",
               cats=COLOR_WEAK_CATS + NO_DISTINCT_EXTRA_CATS, menlei=COLOR_WEAK_MENLEI,
               names=COLOR_WEAK_NAMES + COLOR_BLIND_EXTRA_NAMES,
               basis=f"{P} 二、3", source=S, extends="PR-2003-2-02",
               remark="原文：不能准确识别红、黄、绿、蓝、紫各种颜色中任何一种颜色的导线、按键、"
                      "信号灯、几何图形者不能录取的专业，除同前两类外，还包括经济学类、管理科学"
                      "与工程类、工商管理类、公共管理类、农业经济管理类、图书档案学类各专业；"
                      "不能准确在显示器上识别各颜色的数码、字母者不能录取到计算机科学与技术等专业"
                      "（类级映射为计算机类，粒度差异已注明）。"))
    r.append(R("PR-2003-2-04", "裸眼视力", "视力", "blocker", "national",
               names=["飞行技术", "航海技术", "消防工程", "刑事科学技术", "侦察学"],
               threshold="<5.0",
               basis=f"{P} 二、4", source=S,
               remark="原文：裸眼视力任何一眼低于 5.0 者不能录取飞行技术、航海技术、消防工程、"
                      "刑事科学技术、侦察。专科：海洋船舶驾驶及民航空中交通管制等（见原文）。"
                      "点名的 5 个专业分属交通运输类/公安技术类/公安学类，**不上卷到类**"
                      "（上卷会误伤同类的交通工程、公安视听技术等）。"))
    r.append(R("PR-2003-2-05", "裸眼视力", "视力", "blocker", "national",
               names=["轮机工程", "运动训练", "民族传统体育"],
               threshold="<4.8",
               basis=f"{P} 二、5", source=S,
               remark="原文：裸眼视力任何一眼低于 4.8 者不能录取轮机工程、运动训练、民族传统体育。"
                      "专科：烹饪与营养、烹饪工艺等（见原文）。点名专业不上卷到类。"))

    # ── 第三部分：不宜就读（warning，绝不拦截）──
    r.append(R("PR-2003-3-01", "主要脏器手术史/相关病史（心脏病除外情形等）", "手术史/脏器",
               "warning", "national", cats=ORGAN_CATS, names=ORGAN_NAMES,
               basis=f"{P} 三、1", source=S, ready=False,
               remark="原文：肺、肝、肾、脾、胃肠等动过较大手术功能恢复良好，或曾患心肌炎、"
                      "胃或十二指肠溃疡、慢性支气管炎、风湿性关节炎等病史，甲状腺机能亢进已治愈"
                      "一年者，不宜就读本文所列专业。**不宜就读≠不予录取**：原文明确『学校不得以"
                      "此为依据，拒绝录取达到相关要求的考生』。",
               note="档案无手术史/病史字段，仅供展示/人工核查，不参与判档。"))
    r.append(R("PR-2003-3-02", "先天性心脏病经手术治愈（或确认无需手术者）", "心血管",
               "warning", "national", cats=ORGAN_CATS, names=ORGAN_NAMES,
               basis=f"{P} 三、2", source=S, extends="PR-2003-3-01", ready=False,
               remark="原文：不宜就读的专业同第三部分第 1 条。",
               note="档案无对应字段，仅供展示/人工核查，不参与判档。"))
    r.append(R("PR-2003-3-03", "肢体残疾（不继续恶化）", "肢体",
               "warning", "national", cats=ORGAN_CATS, names=ORGAN_NAMES,
               basis=f"{P} 三、3", source=S, extends="PR-2003-3-01", ready=False,
               remark="原文：不宜就读的专业同第三部分第 1 条。"
                      "另注：指导意见总则明确高校不得以不具备办学条件为由拒收确能进行所报专业"
                      "学习的残疾考生（补充规定须在招生章程公布）。",
               note="档案无对应字段，仅供展示/人工核查，不参与判档（亦不得据此拦截）。"))
    r.append(R("PR-2003-3-04", "矫正视力", "视力", "warning", "national",
               names=D400_NAMES, threshold="矫正到4.8镜片度数>400度",
               basis=f"{P} 三、4", source=S, ready=False,
               remark="原文：屈光不正任何一眼矫正到 4.8、镜片度数大于 400 度，不宜就读本文所列专业。"
                      "档案暂无『矫正度数』字段——需 T6/T8 视情况扩展档案后再挂载。",
               note="档案缺『矫正度数』字段，建议 T6 暂不挂载（保持不判档）或补档案字段。"
                    "**严禁用裸眼视力字段替代矫正度数求值**。"))
    r.append(R("PR-2003-3-05", "矫正视力", "视力", "warning", "national",
               cats=D800_CATS, menlei=D800_MENLEI, names=D800_NAMES,
               threshold="矫正到4.8镜片度数>800度",
               basis=f"{P} 三、5", source=S, ready=False,
               remark="原文：任何一眼矫正到 4.8、镜片度数大于 800 度，不宜就读本文所列专业。"
                      "档案暂无『矫正度数』字段，同 PR-2003-3-04。"))
    r.append(R("PR-2003-3-06", "矫正视力", "视力", "warning", "national",
               menlei=BLIND_EYE_MENLEI, names=BLIND_EYE_NAMES,
               threshold="一眼失明另一眼矫正到4.8镜片度数>400度",
               basis=f"{P} 三、6", source=S, ready=False,
               remark="原文：一眼失明另一眼矫正 4.8、镜片度数大于 400 度，不宜就读工学、农学、"
                      "医学、法学各专业及应用物理学、应用化学、生物技术、地质学、生态学、环境"
                      "科学、海洋科学、海洋技术、生物科学、应用心理学等专业。门类级（工学/农学/"
                      "医学/法学）按现行专业目录展开到类。"))
    r.append(R("PR-2003-3-07", "听力", "听力", "warning", "national",
               cats=HEARING_CATS, menlei=HEARING_MENLEI, names=HEARING_NAMES,
               threshold="两耳听力均<3米，或一耳5米另一耳全聋",
               basis=f"{P} 三、7", source=S,
               remark="原文：不宜就读法学各专业、外国语言文学各专业以及外交学、新闻学、侦察学、"
                      "学前教育、音乐学、录音艺术、土木工程、交通运输、动物医学各专业、医学各专业。"
                      "档案为二元状态（正常/异常），引擎按粗粒度求值（异常即提示），不能区分 3 米/5 米。",
               note="档案 hearing 仅『正常/异常』二值，无法区分 3 米/5 米阈值——属**粗判**，"
                    "提示文案须写明『以实际听力检查结论为准』。"))
    for suffix, cond, group in (("a", "嗅觉", "嗅觉"), ("b", "口吃", "口吃"),
                                ("c", "步态异常/驼背/面部疤痕等外观情形", "外观")):
        r.append(R(f"PR-2003-3-08{suffix}", cond, group, "warning", "national",
                   cats=FACE_CATS, names=FACE_NAMES,
                   basis=f"{P} 三、8", source=S,
                   ready=(suffix in ("a", "b")),
                   remark="原文同一条款：嗅觉迟钝、口吃、步态异常、驼背，面部有疤痕、血管瘤、"
                          "黑色素痣、白癜风的，不宜就读教育学类、公安学类各专业以及外交学、法学、"
                          "新闻学、音乐表演、表演各专业。按可核查性拆分为三个条件条目（拆分不改语义）。",
                   note="" if suffix in ("a", "b") else "档案无对应字段，仅供展示。"))
    for suffix, cond, group, ready in (("a", "斜视", "视力", False),
                                       ("b", "嗅觉", "嗅觉", True),
                                       ("c", "口吃", "口吃", True)):
        r.append(R(f"PR-2003-3-09{suffix}", cond, group, "warning", "national",
                   menlei=MED9_MENLEI, basis=f"{P} 三、9", source=S, ready=ready,
                   remark="原文：斜视、嗅觉迟钝、口吃的，不宜就读医学类专业。"
                          "按可核查性拆分（拆分不改语义）。",
                   note="" if ready else "档案无对应字段，仅供展示。"))

    # ── 军队院校（《军队选拔军官和文职人员体检标准》通用标准）──
    r.append(R("PR-ARMY-01", "身高", "身高体重", "blocker", "military",
               threshold="男<162cm；女<158cm", basis=f"{BASIS_ARMY} 第二章第三节 第三条",
               source=SOURCE_ARMY, ready=False,
               remark="军队院校招收普通高中毕业生执行该标准（军检单独组织）。"
                      "女性标准 158cm（注意部分旧文引 2017 版为 160cm，本表按现行版）。",
               note="档案无性别字段且引擎身高判定无性别维度——T6 挂载前需补性别过滤。"))
    r.append(R("PR-ARMY-02", "体重指数", "身高体重", "blocker", "military",
               threshold="男 BMI<17.5 或 ≥30；女 BMI<17 或 ≥24", 
               basis=f"{BASIS_ARMY} 第二章第三节 第四条", source=SOURCE_ARMY, ready=False,
               remark="原文为 BMI 区间不合格（附空腹血糖/糖化血红蛋白条件），超出引擎单边体重"
                      "比较能力，需引擎扩展后求值。",
               note="引擎 weight 判定为单边 min 比较，不支持 BMI 区间；需 T6 扩展（身高+体重求 BMI）。"))
    r.append(R("PR-ARMY-03", "裸眼视力", "视力", "blocker", "military",
               threshold="<4.5", basis=f"{BASIS_ARMY} 第二章第三节 眼科项目", source=SOURCE_ARMY,
               ready=False,
               remark="双眼中任何一眼裸眼视力小于 4.5，不合格。",
               note="引擎视力判定线仅支持 5.0/4.8，**4.5 线需 T6 在 _VISION_THRESHOLDS 增加**，"
                    "否则会按默认 5.0 误拦（过度拦截）。"))
    r.append(R("PR-ARMY-04", "裸眼视力", "视力", "blocker", "military",
               threshold="裸眼4.5~4.8 且矫正<4.8 或矫正度数>600度",
               basis=f"{BASIS_ARMY} 第二章第三节 眼科项目", source=SOURCE_ARMY, ready=False,
               remark="双眼中任何一眼裸眼视力小于 4.8 时需进行矫正视力检查，任何一眼矫正视力"
                      "低于 4.8 或矫正度数超过 600 度，不合格。档案无矫正度数字段。"))
    r.append(R("PR-ARMY-05", "色弱、色盲", "色觉", "blocker", "military",
               basis=BASIS_ARMY, source=SOURCE_ARMY, ready=False,
               remark="军队体检色觉标准原文未完整核到（本轮资料仅核到通用标准外科/眼科摘录），"
                      "**宁缺不猜**：色觉具体条款待取到标准全文后补充；本条为占位提示，不参与判档。",
               note="占位条目：原文未核到，不导入、不判档。"))

    # ── 公安院校（《公安院校公安专业招生体检标准》2025 版）──
    r.append(R("PR-POLICE-01", "身高", "身高体重", "blocker", "police",
               threshold="男<170cm；女<160cm", basis=f"{BASIS_POLICE} 第一章 第一条",
               source=SOURCE_POLICE, ready=False,
               remark="男性身高小于 170 厘米、女性小于 160 厘米不合格（警检单独组织）。",
               note="同 PR-ARMY-01：需性别维度。"))
    r.append(R("PR-POLICE-02", "体重指数", "身高体重", "blocker", "police",
               threshold="男 BMI<17.3 或 >27.3；女 BMI<17.1 或 >25.7",
               basis=f"{BASIS_POLICE} 第一章 第二条", source=SOURCE_POLICE, ready=False,
               remark="BMI 区间不合格，需引擎扩展后求值。"))
    r.append(R("PR-POLICE-03", "裸眼视力", "视力", "blocker", "police",
               threshold="<4.8", basis=f"{BASIS_POLICE} 第三章 眼科",
               source=SOURCE_POLICE,
               remark="双眼中任何一眼裸眼视力小于 4.8 不合格（2025 版标准）。"))
    r.append(R("PR-POLICE-04", "色弱", "色觉", "blocker", "police",
               basis=f"{BASIS_POLICE} 第三章 眼科", source=SOURCE_POLICE,
               remark="色弱不合格（针对公安院校公安专业，非普适类专业限制）。"))
    r.append(R("PR-POLICE-05", "色盲", "色觉", "blocker", "police",
               basis=f"{BASIS_POLICE} 第三章 眼科", source=SOURCE_POLICE,
               remark="色盲不合格（针对公安院校公安专业，非普适类专业限制）。"))
    r.append(R("PR-POLICE-06", "听力", "听力", "blocker", "police",
               basis=f"{BASIS_POLICE} 第四章 耳鼻咽喉科", source=SOURCE_POLICE,
               remark="双耳中任何一耳耳语听力小于 5 米不合格。档案 hearing 为二值，粗判。",
               note="档案 hearing 仅『正常/异常』二值——粗判，提示文案须写明以实际检查为准。"))
    return r


# ── 已废止/被取代条目（不导入、不判档；保留以供溯源）──
def build_superseded() -> list[dict]:
    return [{
        "rule_id": "PR-HIST-HEPB",
        "condition": "乙肝表面抗原携带",
        "condition_group": "传染性疾病",
        "severity_original": "blocker",
        "status": "superseded",
        "status_basis": "《教育部办公厅 卫生部办公厅关于普通高等学校招生学生入学身体检查"
                        "取消乙肝项目检测有关问题的通知》（教学厅〔2010〕2号）第一条：取消"
                        "『乙型肝炎表面抗原携带者不能录取学前教育、航海技术、飞行技术、面点工艺、"
                        "西餐工艺、烹饪与营养、烹饪工艺、食品科学与工程专业』的限制；第二条："
                        "取消乙肝项目检测（乙肝五项/HBV-DNA），保留丙氨酸氨基转移酶（ALT）检测。",
        "original_basis": f"{BASIS_GUIDE} 二、6（2003 年原文）",
        "remark": "该条 2010 年起不再执行，**不得导入规则库、不得参与判档**（否则属过度拦截）。"
                  "现档案字段 hepatitis_b 无有效规则对应；『慢性肝炎且肝功能不正常』见 PR-2003-1-05"
                  "（ALT 口径）。此条保留仅为评审溯源展示与测试反例之用。",
    }]


def load_major_index() -> tuple[dict, set, dict]:
    """载入专业库索引 → (name2info, valid_classes, menlei2classes)。

    **离线可复跑（红线）**：仓库内 `data/majors/majors.json`
    （845 专业 / 93 专业类 / 12 门类，随仓库分发）为**必需基线**，缺失即报错。
    仓库外整合产物 `merged/major.json`（938 专业，同一「name/first_class/code」
    口径）若存在则并入，以扩大点名专业的覆盖面；**缺失只提示、不报错**。

    已核验两者等价性（PR 说明留档）：93 个专业类与 12 个门类的「门类→类展开面」
    逐项一致；本文件引用的 44 个类、4 个门类、79 个点名专业的
    「名称 → 专业类 / 专业代码」解析结果**零差异**。故并入与否不改变产出。
    """
    catalog = json.loads(CATALOG_MAJOR.read_text(encoding="utf-8"))

    name2info: dict[str, dict] = {}
    valid_classes: set[str] = set()
    menlei2classes: dict[str, set] = {}

    def _feed(name: str, klass: str, menlei: str, code: str) -> None:
        if name and klass and name not in name2info:
            name2info[name] = {"class": klass, "code": code}
        if klass:
            valid_classes.add(klass)
            if menlei:
                menlei2classes.setdefault(menlei, set()).add(klass)

    for r in catalog.get("majors", []):                      # 基线：仓库内
        _feed((r.get("name") or "").strip(), (r.get("class_name") or "").strip(),
              (r.get("menlei") or "").strip(), (r.get("code") or "").strip())

    if MERGE_MAJOR.exists():                                 # 可选：仓库外整合产物
        merged = json.loads(MERGE_MAJOR.read_text(encoding="utf-8"))
        mrecs = merged.get("records") or merged.get("rows") or []
        for r in mrecs:
            _feed((r.get("name") or "").strip(), (r.get("first_class") or "").strip(),
                  (r.get("category") or "").strip(), (r.get("code") or "").strip())
        print(f"[lib ] 并入仓库外整合产物 {MERGE_MAJOR}（{len(mrecs)} 专业）")
    else:
        print(f"[lib ] 仓库外整合产物不在本机（{MERGE_MAJOR}）——"
              f"按仓库内基线 {CATALOG_MAJOR.name} 运行，产出不受影响")

    if not name2info or not valid_classes or not menlei2classes:
        raise SystemExit(f"[err] 专业库为空：{CATALOG_MAJOR}（离线可复跑依赖此文件）")
    print(f"[lib ] 专业 {len(name2info)} / 专业类 {len(valid_classes)} / 门类 {len(menlei2classes)}")
    return name2info, valid_classes, menlei2classes


def main() -> int:
    # ── 载入专业库 ──
    name2info, valid_classes, menlei2classes = load_major_index()
    valid_menlei = set(menlei2classes)

    # ── 组装 + 校验 ──
    rules = build_rules()
    problems: list[str] = []
    for rule in rules:
        rid = rule["rule_id"]
        if rule["severity"] not in ("blocker", "warning"):
            problems.append(f"{rid}: severity 非法 {rule['severity']}")
        if not rule["basis"]:
            problems.append(f"{rid}: 缺 basis")
        for cat in rule["major_categories"]:
            if cat not in valid_classes:
                problems.append(f"{rid}: 类不存在于专业库：{cat}")
        for m in rule["major_menlei"]:
            if m not in valid_menlei:
                problems.append(f"{rid}: 门类不存在：{m}")
        if rule["engine_ready"] and rule["condition"] not in KEYS and not any(
                k in rule["condition"] for k in KEYS):
            problems.append(f"{rid}: engine_ready=true 但 condition 不匹配引擎条件键：{rule['condition']}")
        # 点名专业解析（旧名→别名→专业库；全部要能落位）
        trace, missing = [], []
        for n in rule["major_names"]:
            canon = MAJOR_ALIAS.get(n, n)
            info = name2info.get(canon)
            if info:
                trace.append({"name_in_text": n, "catalog_name": canon,
                              "class": info["class"], "code": info["code"]})
            else:
                missing.append(n)
        rule["major_trace"] = trace
        if missing:
            problems.append(f"{rid}: 点名专业无法映射：{missing}")

    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        return 1

    # 门类 → 类展开（供校验与前端展示）
    for rule in rules:
        rule["major_classes_expanded"] = sorted(
            set(rule["major_categories"])
            | {c for m in rule["major_menlei"] for c in menlei2classes.get(m, set())}
            | {t["class"] for t in rule["major_trace"]}
        )

    doc = {
        "meta": {
            "title": "体检专业限制映射表（physical_restriction，闸门③弹药）",
            "generated_at": "2026-10-15",
            "contract_ref": "docs/api-contract.md §8.7 physical_restriction；"
                            "引擎消费：backend/app/engine/constraints.py physical_check / "
                            "种子形状：backend/app/services/constraint_seed.py PHYSICAL_RULES",
            "sources": [
                {"id": SOURCE_GUIDE, "name": BASIS_GUIDE,
                 "url": "https://gaokao.chsi.com.cn/zxdy/view--qid-436737,method-listBulletin,"
                        "showCurrent-ggq1,year-2005,start-0.dhtml",
                 "year": 2003, "source_type": "官方",
                 "note": "教育部、卫生部、中国残联印发；现行版全文经地方政府2026年体检通知附件核对。"},
                {"id": SOURCE_HEPB, "name": "教育部办公厅、卫生部办公厅《关于普通高等学校招生学生"
                                            "入学身体检查取消乙肝项目检测有关问题的通知》（教学厅〔2010〕2号）",
                 "url": "https://www.moe.gov.cn/srcsite/A15/moe_776/s3258/201002/t20100225_87433.html",
                 "year": 2010, "source_type": "官方",
                 "note": "取消乙肝限制条款与乙肝检测，保留 ALT。"},
                {"id": SOURCE_ARMY, "name": "《军队选拔军官和文职人员体检标准》（军队院校招生执行，"
                                            "经教育部阳光高考平台转载摘录）",
                 "url": "https://gaokao.chsi.com.cn/gkxx/zc/ss/202506/20250619/2293390263.html",
                 "year": 2025, "source_type": "官方", "note": "军检单独组织，属专项资格。"},
                {"id": SOURCE_POLICE, "name": "《公安院校公安专业招生体检标准》（公安部，2025年执行版，"
                                              "经教育部阳光高考平台转载）",
                 "url": "https://gaokao.chsi.com.cn/gkxx/zc/ss/202506/20250624/2293390562.html",
                 "year": 2025, "source_type": "官方", "note": "警检单独组织，属专项资格。"},
            ],
            "分级口径": {
                "blocker": "原文『学校（有关专业）可不予录取』——报得上可能被退档（拒绝录取）",
                "warning": "原文『不宜就读』——知情提示；原文明确『学校不得以此为依据，拒绝录取"
                           "达到相关要求的考生』，**绝不拦截**",
                "铁律": "不得把 warning 错标成 blocker，反之亦然；scope=military/police 的条目仅适用"
                        "于军校/公安院校（单独军检警检），**不得用于普通批次志愿判档**",
            },
            "范围口径": {
                "专业库": "本科专业目录（major 表 938 专业 / 93 专业类）；专科专业清单见原文，不在本表",
                "类级 vs 点名": "原文点名『X类各专业』→ major_categories（类级）；原文枚举具体专业 → "
                                "major_names（专业级，不上卷到类，避免过度拦截）",
                "门类级": "原文『工学/农学/医学/法学各专业』→ major_menlei（导入时按专业库展开到类）",
            },
            "engine_integration": {
                "当前可求值（engine_ready=true）": "色系（色弱/色盲/不能识别）三类、裸眼视力 5.0/4.8 "
                                                   "两线、听力/嗅觉/口吃（二值粗判）、公安 4.8 线",
                "需 T6 引擎扩展后才可求值": [
                    "PR-ARMY-03（4.5 视力线：_VISION_THRESHOLDS 需加 '<4.5'，否则默认 5.0 会误拦）",
                    "PR-ARMY-02 / PR-POLICE-02（BMI 区间：现有 weight 判定为单边 min 比较）",
                    "PR-ARMY-01 / PR-POLICE-01（身高含性别维度：需档案补 gender 并按性别过滤规则）",
                    "PR-2003-3-04/05/06（矫正度数：档案无『矫正度数』字段）",
                ],
                "不导入不判档": "superseded 区（PR-HIST-HEPB）、PR-ARMY-05（占位）、"
                               "universal 条目（体检结论类，档案无法覆盖，仅供展示）",
                "库表约定": "national/military/police 条目入库时 province_code=''（全国通用，"
                            "管理端列表接口对空省码按通用返回）；军校/公安条目 condition 入库时"
                            "加后缀『（军队院校）/（公安院校）』以与普适同类条件区分",
            },
            "self_check": {
                "每条规则有 basis": True,
                "blocker/warning 与指导意见三部分对应": "一/二部分→blocker，三部分→warning",
                "色觉条目覆盖主要受限类": ["医学类（门类展开）", "化学类", "生物科学类", "公安技术类",
                                          "药学类", "地质学类"],
                "乙肝条目": "已被教学厅〔2010〕2号取代 —— 保留于 superseded 区并注明废止依据，"
                            "**不按 blocker 导入**（任务书自查项据此修正，政策依据见 status_basis）",
                "河南/江西体检表项目覆盖": ["视力→裸眼视力/矫正视力条目", "色觉→色弱/色盲/不能识别",
                                            "身高→军队/公安条目", "肝功能→PR-2003-1-05（ALT 口径）",
                                            "听力/嗅觉→第三部分条目"],
                "未取到依据未编造": ["军队色觉条款（PR-ARMY-05 占位，待标准全文）",
                                     "师范类身高（无国家统一标准，属院校章程事项，不录）"],
            },
        },
        "rules": rules,
        "superseded": build_superseded(),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    n_b = sum(1 for x in rules if x["severity"] == "blocker")
    n_w = len(rules) - n_b
    print(f"[ok] {OUT_PATH}")
    print(f"[ok] 规则 {len(rules)} 条（blocker {n_b} / warning {n_w}），"
          f"另 superseded {len(doc['superseded'])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())

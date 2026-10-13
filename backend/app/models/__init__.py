"""ORM 模型集合。

导入本包即把所有模型注册到 Base.metadata，alembic 与环境初始化依赖这一点。
新增模型务必在此登记，否则不会被迁移脚本创建。

表清单与产品书第 7 章「数据模型与数据字典」一一对应：
- 7.1 基础数据：source / school / major / school_major_score / score_segment /
  enrollment_rule / discipline_eval
- 7.2 升学途径：pathway / pathway_eligibility / pathway_region / pathway_score
- 7.3 用户系统：users、profiles（0001 迁移） + user_favorite / user_plan
- 7.4 院校画像：school_profile / school_life
- 7.5 知识库与运营：knowledge_doc / knowledge_chunk / qa_log / review_task / admin_user
- 7.6 报考约束：province_exam_rule / subject_requirement / physical_restriction
  （0007 追加 admission_requirement / major_tuition / rule_dataset_status，对齐契约 8.7）
- 8.1 管理端运营：admin_audit_log（第 7 章未定义，为「操作留痕」验收新增，见 app/models/audit.py）
- 8.3 管理端运营：index_task（第 7 章未定义，为索引重建的任务态与进度新增，见 app/models/knowledge.py）
"""

from __future__ import annotations

from app.models.audit import AdminAuditLog
from app.models.base_data import (
    DisciplineEval,
    EnrollmentRule,
    Major,
    School,
    SchoolMajorScore,
    ScoreSegment,
)
from app.models.constraints import (
    AdmissionRequirement,
    MajorTuition,
    PhysicalRestriction,
    ProvinceExamRule,
    RuleDatasetStatus,
    SubjectRequirement,
)
from app.models.knowledge import (
    AdminUser,
    IndexTask,
    KnowledgeChunk,
    KnowledgeDoc,
    QaLog,
    ReviewTask,
)
from app.models.pathway import (
    Pathway,
    PathwayEligibility,
    PathwayRegion,
    PathwayScore,
)
from app.models.profile import Profile
from app.models.school_profile import SchoolLife, SchoolProfile
from app.models.source import Source
from app.models.user import User
from app.models.user_data import UserFavorite, UserPlan

__all__ = [
    "AdminAuditLog",
    "AdminUser",
    "AdmissionRequirement",
    "DisciplineEval",
    "EnrollmentRule",
    "IndexTask",
    "KnowledgeChunk",
    "KnowledgeDoc",
    "Major",
    "MajorTuition",
    "Pathway",
    "PathwayEligibility",
    "PathwayRegion",
    "PathwayScore",
    "PhysicalRestriction",
    "Profile",
    "ProvinceExamRule",
    "QaLog",
    "ReviewTask",
    "RuleDatasetStatus",
    "School",
    "SchoolLife",
    "SchoolMajorScore",
    "SchoolProfile",
    "ScoreSegment",
    "Source",
    "SubjectRequirement",
    "User",
    "UserFavorite",
    "UserPlan",
]

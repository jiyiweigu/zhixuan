declare namespace Zhixuan {
 interface ApiResponse<T>{code:number;message:string;data:T;trace_id:string}
 interface Page<T>{items:T[];total:number;page:number;page_size:number}
 interface Citation{index?:number;chunk_id?:string;source_name:string;source_url:string;year:number;snippet?:string}
 // 契约 8.1：可空档案项统一用 null 表示未提供（不再使用 "未填" / "未知" 哨兵字符串）
 // 契约 2：GET/PUT /api/user/profile 全量字段。has_*_special 为只读派生字段（由 special_marks 与户籍/学籍推出），不作入参。
 interface Profile{profile_id?:number;province:string;exam_type?:'普通'|'艺术'|'体育'|null;first_subject?:'物理'|'历史'|null;second_subjects?:string[]|null;subject_type?:string;score:number|null;rank?:number|null;household_type?:'城镇'|'农村'|null;home_county?:string|null;home_county_code?:string|null;school_years?:number|null;enrollment_county?:string|null;household_years?:number|null;enrollment_years?:number|null;parent_household_local?:boolean|null;has_national_special?:boolean;has_local_special?:boolean;has_college_special?:boolean;special_marks?:string[];preferred_cities?:string[];preferred_majors?:string[];tuition_budget?:number|null;color_vision?:'正常'|'色弱'|'色盲'|'不能识别红黄绿蓝紫任一色'|null;vision_left?:number|null;vision_right?:number|null;height?:number|null;weight?:number|null;hepatitis_b?:boolean|null;hearing?:'正常'|'异常'|null;smell?:'正常'|'异常'|null;stutter?:'正常'|'异常'|null;batch_preference?:string[]|null;accept_adjustment?:boolean|null;updated_at?:string;completeness?:{percent:number;missing:string[]};preferences?:{strategy?:string;priority?:'城市优先'|'专业优先'|'院校优先';preferred_majors?:string[];preferred_cities?:string[];preferred_provinces?:string[];major_adjust?:boolean;accept_adjustment?:boolean|null}}
 interface User{user_id:number|string;username:string;role?:'user'|'admin'}
 interface AuthResult{token?:string;access_token?:string;expires_in?:number;user?:User;admin?:User;user_id?:number|string;username?:string}
 // 契约 8.1：data_status 取值 available | partial | schema_only | unavailable
 interface Pathway{pathway_id:number|string;name:string;category:string;batch:string;target_group:string;apply_time:string;priority:'P0'|'P1'|'P2';status?:string;data_status:'available'|'partial'|'schema_only'|'unavailable';source_name?:string;source_url?:string;year?:number;sources?:Citation[];description?:string;conditions?:Array<{text:string;source_name:string;source_url:string}>;timeline?:Array<{node:string;date_desc:string}>}
 interface ConstraintHit{type:string;level:'reject'|'not_suitable'|'soft'|'unknown';detail:string;major_ids?:Array<number|string>;major_names?:string[];fields?:string[];citation?:Citation}
 interface EligibilityResult{pathway_id?:number|string;pathway_name?:string;unit_id?:string;school_name?:string;group_code?:string|null;eligible:boolean|null;reason?:string;rules?:Array<{rule_type:string;rule_desc:string;source_name:string;source_url:string;year?:number}>;risk_note?:string|null;blockers?:ConstraintHit[];warnings?:ConstraintHit[];unknowns?:ConstraintHit[];citations?:Citation[]}
 interface Eligibility{results:EligibilityResult[];updated_profile?:Profile;citations?:Citation[]}
 interface EligibilityCheckResp{data_status:'available'|'partial'|'schema_only'|'unavailable';items:EligibilityResult[];summary:{total:number;blocked:number;warned:number;unknown:number};missing_rule_sets?:string[]}
 // 契约 4：confidence 为 0~1 数值；confidence_level 为同一判定的三档结果，供徽标直接使用
 interface QaResult{qa_log_id:number|string;session_id:string|null;question?:string;answer:string;citations:Citation[];confidence:number;confidence_level:'high'|'medium'|'low';needs_review:boolean;degraded:boolean;elapsed_ms:number;created_at?:string|null}
 // 契约 4：GET /api/qa/history 的 items[]。注意史册条目的 confidence 是**三档字符串**（非 0~1 数值），以接口为准。
 interface QaHistoryItem{qa_log_id:number|string;session_id:string|null;question:string;answer:string;confidence:string;confidence_level?:string;citations:Citation[];needs_review:boolean;degraded:boolean;created_at:string|null}
 // 契约 8.4/8.5：校验请求的志愿单位（院校专业组）。
 interface EligibilityUnit{unit_id:string;batch?:string;school_id?:number|string|null;group_code?:string|null;major_ids?:Array<number|string>;school_name?:string}
 interface PlanItem{tier:'冲'|'稳'|'保';order:number;school_id:number|string;school_name:string;group_code:string|null;major_ids:number[];major_names:string[];min_score_ref:number|null;min_rank_ref:number|null;ref_year:number|null;gap_rank:number|null;source_note:string;source_name?:string;source_url?:string;year?:number}
 // 契约 5/6.1：tiers 为各档实际数量（志愿条目本身在 items 中，按 item.tier 分组）
 interface Recommendation{strategy:string;priority?:string;tiers:Record<string,number>;quota?:Record<string,number>;items?:PlanItem[];risk_notes?:string[];citations?:Citation[];data_status?:string;disclaimer?:string;summary?:string;generated_at?:string}
 // 契约 6.1：每条风险含级别 / 类型 / 目标 / 说明 / 规则来源
 interface Risk{level:'high'|'medium'|'low';type?:string;code?:string;target?:string;detail?:string;message?:string;title?:string;evidence?:string;remedy?:string;citation?:Citation;rule_source?:string}
 interface Favorite{favorite_id:number|string;target_type:'school'|'major';target_id:string;target_name:string;created_at:string|null}
 interface ScoreSegment{province:string;year:number;subject_type:string;data_status:'available'|'partial'|'schema_only'|'unavailable';score:number|null;cumulative_rank:number|null;same_score_count:number|null;citations:Citation[];missing_rule_sets?:string[]}
 interface School{school_id:number|string;name:string;code:string;province:string;city:string;level:string;type:string;ownership:string;website?:string;intro?:string;sources?:Citation[];citations?:Citation[]}
 interface Major{major_id:number|string;name:string;code:string;category:string;degree:string;intro?:string;first_class_schools?:string[]}
 interface ConfidenceBadgeProps {level:'high'|'medium'|'low';score?:number}
 // ===================== 管理端（契约 v1.4：附录 A + §8.8）=====================
 // data_status 唯一词表（契约「跨层词表」）：available | partial | schema_only | unavailable
 type DataStatus='available'|'partial'|'schema_only'|'unavailable'
 // 语料列表项（后端 corpus.doc_item；source_url/chunk_count 为实现追加字段）
 interface AdminDoc{doc_id:number;title:string;source_name:string;source_url?:string;year:number;doc_type:string;province:string;pathway_id:string|null;chunk_count:number;created_at:string|null}
 // 语料导入入参（后端 DocCreateRequest：来源三要素平铺在顶层，缺一 → 4001）
 interface DocCreateInput{title:string;source_name:string;source_url:string;year:number;doc_type?:string;province?:string;pathway_id?:string|null;content?:string;chunks?:string[]}
 // 索引任务状态（后端 indexing.task_state：progress 为对象，非数字）
 interface IndexProgress{total:number;processed:number;embedded:number;pending_embedding:number;failed:number;percent:number}
 interface IndexTaskState{task_id:number;status:string;progress:IndexProgress;scope:string;doc_ids:number[];incremental:boolean;message:string|null;embedder_ready:boolean;operator:string|null;created_at:string|null;started_at:string|null;finished_at:string|null}
 interface IndexRebuildInput{scope:'all'|'doc_ids';doc_ids?:number[];incremental?:boolean}
 // 途径字典项（后端 pathway_admin.pathway_item；source 为来源三要素对象）
 interface AdminPathway{pathway_id:string;name:string;category:string;batch:string;target_group:string;apply_time:string;description:string;priority:'P0'|'P1'|'P2';data_status:DataStatus;year:number;source:Citation}
 // 资格规则项（后端 pathway_admin.rule_item）
 interface AdminPathwayRule{rule_id:number;pathway_id:string;province:string;rule_type:'户籍'|'学籍'|'区域'|'成绩';rule_desc:string;params:Record<string,unknown>;year:number;source:Citation}
 // 专项实施区域项（后端 pathway_admin.region_item）
 interface AdminRegion{region_id:number;pathway_id:string;province:string;county_name:string;county_code:string;year:number;source_name:string;source_url:string}
 // 审核任务（列表项 = 后端 review.task_item；详情追加 citations/original_answer 等字段）
 interface ReviewTaskItem{task_id:number;qa_log_id:number;question:string;answer:string;confidence:'high'|'medium'|'low';trigger_reason:string;status:'pending'|'approved'|'corrected'|'rejected';reviewer:string|null;created_at:string|null;citations?:Citation[];degraded?:boolean;session_id?:string|null;user_id?:number|null;original_answer?:string;corrected_answer?:string|null;comment?:string|null;reviewed_at?:string|null;qa_created_at?:string|null}
 // 审核决策入参（后端 ReviewDecisionRequest：action=correct 必须带 corrected_answer）
 interface ReviewDecision{action:'approve'|'correct'|'reject';corrected_answer?:string;comment?:string}
 // 逐途径语料覆盖度（后端 stats.coverage_by_pathway）
 interface PathwayCoverage{pathway_id:string;pathway_name:string;priority:string;doc_count:number;chunk_count:number;covered:boolean}
 interface AdminStats{doc_count:number;chunk_count:number;qa_count:number;low_confidence_count:number;review_pending_count:number;coverage_by_pathway:PathwayCoverage[]}
 // 契约 8.7/8.8：规则数据集与批量导入
 type RuleDataset='province_exam_rule'|'subject_requirement'|'physical_restriction'|'admission_requirement'|'major_tuition'
 interface RuleDatasetStatusItem{rule_id:number;province_code:string;year:number;batch_code:string;exam_type:string;dataset:RuleDataset;status:DataStatus;note:string;updated_at:string|null}
 interface RuleImportPayload{dataset:RuleDataset;province_code:string;year:number;batch_code?:string;exam_type?:'普通'|'艺术'|'体育';items:Record<string,unknown>[]}
 // 导入响应（契约 8.8：{dataset,created,updated,rejected,errors[]}；校验失败整批回滚 → 错误包）
 interface RuleImportResult{dataset:RuleDataset;created:number;updated:number;rejected:number;errors:unknown[]}
}

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
 interface EligibilityResult{pathway_id?:number|string;pathway_name?:string;unit_id?:string;eligible:boolean|null;reason?:string;rules?:Array<{rule_type:string;rule_desc:string;source_name:string;source_url:string;year?:number}>;risk_note?:string|null;blockers?:ConstraintHit[];warnings?:ConstraintHit[];unknowns?:ConstraintHit[];citations?:Citation[]}
 interface Eligibility{results:EligibilityResult[];updated_profile?:Profile;citations?:Citation[]}
 interface EligibilityCheckResp{data_status:'available'|'partial'|'schema_only'|'unavailable';items:EligibilityResult[];summary:{total:number;blocked:number;warned:number;unknown:number};missing_rule_sets?:string[]}
 // 契约 4：confidence 为 0~1 数值；confidence_level 为同一判定的三档结果，供徽标直接使用
 interface QaResult{qa_log_id:number|string;session_id:string|null;question?:string;answer:string;citations:Citation[];confidence:number;confidence_level:'high'|'medium'|'low';needs_review:boolean;degraded:boolean;elapsed_ms:number;created_at?:string|null}
 interface PlanItem{tier:'冲'|'稳'|'保';order:number;school_id:number|string;school_name:string;group_code:string|null;major_ids:number[];major_names:string[];min_score_ref:number|null;min_rank_ref:number|null;ref_year:number|null;gap_rank:number|null;source_note:string;source_name?:string;source_url?:string;year?:number}
 // 契约 5/6.1：tiers 为各档实际数量（志愿条目本身在 items 中，按 item.tier 分组）
 interface Recommendation{strategy:string;priority?:string;tiers:Record<string,number>;quota?:Record<string,number>;items?:PlanItem[];risk_notes?:string[];citations?:Citation[];data_status?:string;disclaimer?:string;summary?:string;generated_at?:string}
 // 契约 6.1：每条风险含级别 / 类型 / 目标 / 说明 / 规则来源
 interface Risk{level:'high'|'medium'|'low';type?:string;code?:string;target?:string;detail?:string;message?:string;title?:string;evidence?:string;remedy?:string;citation?:Citation;rule_source?:string}
 interface Favorite{favorite_id:number|string;target_type:'school'|'major';target_id:string;target_name:string;created_at:string|null}
 interface ScoreSegment{province:string;year:number;subject_type:string;data_status:'available'|'partial'|'schema_only'|'unavailable';score:number|null;cumulative_rank:number|null;same_score_count:number|null;citations:Citation[];missing_rule_sets?:string[]}
 interface School{school_id:number|string;name:string;code:string;province:string;city:string;level:string;type:string;ownership:string;website?:string;intro?:string;sources?:Citation[];citations?:Citation[]}
 interface Major{major_id:number|string;name:string;code:string;category:string;degree:string;intro?:string;first_class_schools?:string[]}
 interface ConfidenceBadgeProps {level:'high'|'medium'|'low'}
}

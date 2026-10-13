declare namespace Zhixuan {
 interface ApiResponse<T>{code:number;message:string;data:T;trace_id:string}
 interface Page<T>{items:T[];total:number;page:number;page_size:number}
 interface Citation{index?:number;chunk_id?:string;source_name:string;source_url:string;year:number;snippet?:string}
 interface Profile{profile_id?:number;province:string;exam_type?:'普通'|'艺术'|'体育';first_subject?:'物理'|'历史';second_subjects?:string[];subject_type?:string;score:number|null;rank?:number|null;household_type?:'城镇'|'农村';home_county?:string;home_county_code?:string;school_years?:number;has_national_special?:boolean;has_local_special?:boolean;has_college_special?:boolean;preferred_cities?:string[];preferred_majors?:string[];tuition_budget?:number|null;updated_at?:string;preferences?:{priority?:'城市优先'|'专业优先';preferred_majors?:string[];preferred_cities?:string[];accept_adjustment?:boolean}}
 interface User{user_id:number|string;username:string;role?:'user'|'admin'}
 interface AuthResult{token?:string;access_token?:string;expires_in?:number;user?:User;admin?:User;user_id?:number|string;username?:string}
 interface Pathway{pathway_id:number|string;name:string;category:string;batch:string;target_group:string;apply_time:string;priority:'P0'|'P1'|'P2';data_status:'available'|'schema_only';source_name?:string;source_url?:string;year?:number;sources?:Citation[];description?:string;conditions?:Array<{text:string;source_name:string;source_url:string}>;timeline?:Array<{node:string;date_desc:string}>}
 interface EligibilityResult{pathway_id:number|string;pathway_name:string;eligible:boolean;reason:string;rules:Array<{rule_type:string;rule_desc:string;source_name:string;source_url:string}>;risk_note:string|null}
 interface Eligibility{results:EligibilityResult[];updated_profile?:Profile;citations?:Citation[]}
 interface QaResult{qa_log_id:number|string;session_id:string;answer:string;citations:Citation[];confidence:'high'|'medium'|'low';needs_review:boolean;degraded:boolean;elapsed_ms:number}
 interface PlanItem{tier:'冲'|'稳'|'保';order:number;school_id:number|string;school_name:string;group_code:string|null;major_ids:number[];major_names:string[];min_score_ref:number|null;min_rank_ref:number|null;ref_year:number|null;gap_rank:number|null;source_note:string;source_name?:string;source_url?:string;year?:number}
 interface Recommendation{strategy:'school'|'major'|'city';tiers:Array<{tier:'冲'|'稳'|'保';items:PlanItem[]}>;generated_at:string;citations?:Citation[]}
 interface Risk{level:'high'|'medium'|'low';type:string;target:string;message:string;rule_source:string}
 interface School{school_id:number|string;name:string;code:string;province:string;city:string;level:string;type:string;ownership:string;website?:string;intro?:string;sources?:Citation[];citations?:Citation[]}
 interface Major{major_id:number|string;name:string;code:string;category:string;degree:string;intro?:string;first_class_schools?:string[]}
 interface ConfidenceBadgeProps {level:'high'|'medium'|'low'}
}

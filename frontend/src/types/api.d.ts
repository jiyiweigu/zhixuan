declare namespace Zhixuan {
 interface ApiResponse<T>{code:number;message:string;data:T;trace_id:string}
 interface Citation{source_name:string;source_url:string;year:number}
 interface Profile{province:string;score:number;subject_type:string}
 interface Eligibility{eligible:string[];pending:string[];ineligible:string[];profile:Profile;citations:Citation[]}
 interface QaResult{answer:string;confidence:number;citations:Citation[]}
 interface Pathway extends Citation{id:string;name:string;status:string}
 interface PlanItem extends Citation{school_id:string;name:string;tier:'冲'|'稳'|'保';risk_level:'low'|'medium'|'high'}
 interface PlanResult{items:PlanItem[];risk_notes:string[];citations:Citation[]}
 interface School extends Citation{school_id:string;name:string;province:string}
}

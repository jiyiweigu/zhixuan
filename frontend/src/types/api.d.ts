declare namespace Zhixuan {
  interface ApiResponse<T> { code:number; message:string; data:T; trace_id:string }
  interface Citation { source_name:string; source_url:string; year:number }
  interface Profile { province:string; score:number; subject_type:string }
  interface Eligibility { eligible:string[]; pending:string[]; profile:Profile; citations:Citation[] }
  interface QaResult { answer:string; confidence:number; citations:Citation[] }
  interface Pathway { id:string; name:string; status:string; source_name:string; source_url:string; year:number }
}

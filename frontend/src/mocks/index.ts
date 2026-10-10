const c={source_name:'演示数据（非官方）',source_url:'https://example.invalid/mock',year:2026}
const envelope=(data:any,trace_id:string)=>({code:0,message:'success',data,trace_id})
export const auth={success:envelope({user_id:'u_demo',username:'demo',access_token:'mock-token'},'mock-auth'),error:{code:1006,message:'用户名已存在',data:null,trace_id:'mock-auth-error'}}
export const profile={success:envelope({province:'河南',score:620,subject_type:'物理类'},'mock-profile'),empty:envelope(null,'mock-profile-empty')}
export const pathways={success:envelope([{id:'normal-batch',name:'普通批',status:'可查询',...c},{id:'special-plan',name:'国家专项计划',status:'待核验',...c}],'mock-pathways'),empty:envelope([],'mock-pathways-empty')}
const base={profile:{province:'河南',score:620,subject_type:'物理类'},citations:[c]}
export const eligibility={eligible:envelope({...base,eligible:['普通批'],pending:[],ineligible:[]},'mock-eligible'),pending:envelope({...base,eligible:['普通批'],pending:['国家专项计划'],ineligible:[]},'mock-pending'),ineligible:envelope({...base,eligible:[],pending:[],ineligible:['国家专项计划']},'mock-ineligible')}
export const qa={success:envelope({answer:'这是演示回答，请以官方发布为准。',confidence:.86,citations:[c]},'mock-qa'),lowConfidence:envelope({answer:'当前资料不足，建议人工核验。',confidence:.42,citations:[c]},'mock-qa-low'),empty:envelope({answer:'',confidence:0,citations:[]},'mock-qa-empty')}
export const plans={success:envelope({items:[{school_id:'mock-001',name:'演示院校',tier:'稳',risk_level:'medium',...c}],risk_notes:['演示数据，仅供开发'],citations:[c]},'mock-plan'),empty:envelope({items:[],risk_notes:[],citations:[]},'mock-plan-empty')}
export const schools={success:envelope([{school_id:'mock-001',name:'演示院校',province:'河南',citations:[c],...c}],'mock-schools'),empty:envelope([],'mock-schools-empty')}
export const error={code:1001,message:'参数错误',data:null,trace_id:'mock-error'}

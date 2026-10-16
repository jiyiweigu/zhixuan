import { fixtures } from '../mocks'
import { request } from '../utils/request'
const mock=import.meta.env.VITE_USE_MOCK!=='false'
// structuredClone 无法克隆 Vue 响应式代理（reactive 数组等），API 载荷均为 JSON 可序列化，故兜底 JSON 深拷贝。
const clone=<T>(v:T):T=>{try{return structuredClone(v as any)}catch{return JSON.parse(JSON.stringify(v))}}
const m=<T>(v:T):Promise<T>=>Promise.resolve(clone(v))
export const api={
 register:(p:any)=>mock?m(fixtures.auth.login):request<any>('/api/auth/register',{method:'POST',body:JSON.stringify(p)}),login:(p:any)=>mock?m(p.role==='admin'?fixtures.auth.admin:fixtures.auth.login):request<any>(p.role==='admin'?'/api/admin/login':'/api/auth/login',{method:'POST',body:JSON.stringify(p)}),logout:()=>mock?m(null):request('/api/auth/logout',{method:'POST'}),me:()=>mock?m(fixtures.auth.login.user):request('/api/auth/me'),
 getProfile:()=>mock?m(fixtures.profile.profile):request('/api/user/profile'),updateProfile:(p:any)=>mock?m({...fixtures.profile.profile,...p,updated_at:new Date().toISOString()}):request('/api/user/profile',{method:'PUT',body:JSON.stringify(p)}),deleteAccount:(p:any)=>mock?m(null):request('/api/user',{method:'DELETE',body:JSON.stringify(p)}),
 pathways:(q:any={})=>mock?m(fixtures.pathways.items):request(`/api/pathways${qs(q)}`),pathwayDetail:(id:string)=>mock?m(fixtures.pathways.detail):request(`/api/pathways/${id}`),regions:(id:string,p:string)=>mock?m(fixtures.pathways.regions):request(`/api/pathways/${id}/regions${qs({province:p})}`),regionCheck:(p:any)=>mock?m({in_region:false,region_name:null,citations:[]}):request(`/api/pathways/region-check${qs(p)}`),eligibility:(p:any,auth=false)=>mock?m(fixtures.eligibility.data):request(auth?'/api/user/eligibility/check':'/api/eligibility/check',{method:'POST',body:JSON.stringify(p)}),
 ask:(p:any)=>mock?m(/(涨分|会不会|保底|敢报|预测|推测)/.test(p?.question||'')?fixtures.qa.low:fixtures.qa.answer):request<any>('/api/qa/ask',{method:'POST',body:JSON.stringify(p)}),qaHistory:(q:any={})=>mock?m(fixtures.qa.history):request<any>(`/api/qa/history${qs(q)}`),
 recommend:(p:any)=>mock?m(fixtures.recommendation):request('/api/recommend',{method:'POST',body:JSON.stringify(p)}),generatePlan:(p:any)=>mock?m(fixtures.recommendation):request('/api/plans',{method:'POST',body:JSON.stringify(p)}),riskCheck:(p:any)=>mock?m({risks:[]}):request('/api/plan/risk-check',{method:'POST',body:JSON.stringify(p)}),scoreSegment:(q:any)=>mock?m({score:q.score,cumulative_rank:18000,same_score_count:200,...citeMock}):request(`/api/scores/segment${qs(q)}`),
 plans:()=>mock?m(fixtures.plans.items):request('/api/user/plans'),plan:(id:string)=>mock?m(fixtures.plans.detail):request(`/api/user/plans/${id}`),savePlan:(p:any)=>mock?m({plan_id:1}):request('/api/user/plans',{method:'POST',body:JSON.stringify(p)}),updatePlan:(id:string,p:any)=>mock?m(null):request(`/api/user/plans/${id}`,{method:'PUT',body:JSON.stringify(p)}),deletePlan:(id:string)=>mock?m(null):request(`/api/user/plans/${id}`,{method:'DELETE'}),
 schools:(q:any={})=>mock?m(fixtures.school.list):request(`/api/schools${qs(q)}`),school:(id:string)=>mock?m(fixtures.school.detail):request(`/api/schools/${id}`),schoolProfile:(id:string)=>mock?m(fixtures.school.profile):request(`/api/schools/${id}/profile`),schoolLife:(id:string,q:any={})=>mock?m(fixtures.school.life):request(`/api/schools/${id}/life${qs(q)}`),compareSchools:(ids:any[])=>mock?m({items:fixtures.school.list.items}):request('/api/schools/compare',{method:'POST',body:JSON.stringify({school_ids:ids})}),majors:(q:any={})=>mock?m(fixtures.majors.list):request(`/api/majors${qs(q)}`),major:(id:string)=>mock?m(fixtures.majors.detail):request(`/api/majors/${id}`),
 favorites:()=>mock?m(fixtures.favorites.items):request('/api/user/favorites'),addFavorite:(p:any)=>mock?m({favorite_id:1}):request('/api/user/favorites',{method:'POST',body:JSON.stringify(p)}),removeFavorite:(p:any)=>mock?m(null):request(`/api/user/favorites${qs(p)}`,{method:'DELETE'}),
 // ===================== 管理端（契约 v1.4：附录 A + §8.8；后端路由见 backend/app/api/v1/admin/） =====================
 // —— 语料管理（admin/docs.py）：GET 支持 province/year/pathway_id/doc_type/keyword 分页过滤 ——
 adminDocs:(q:any={})=>mock?m(fixtures.admin.docs):request(`/api/admin/docs${qs(q)}`),
 // 语料导入：后端 DocCreateRequest 为 JSON body（来源三要素平铺顶层；缺一 → 4001），不是 multipart
 uploadDoc:(p:any)=>mock?m({doc_id:1,chunk_count:0}):request('/api/admin/docs',{method:'POST',body:JSON.stringify(p)}),
 deleteDoc:(id:string|number)=>mock?m(null):request(`/api/admin/docs/${id}`,{method:'DELETE'}),
 // —— 索引管理（admin/index.py）：rebuild → {task_id,status}；tasks/{id} → progress 为对象 ——
 rebuildIndex:(p:any)=>mock?m({task_id:1,status:'queued'}):request('/api/admin/index/rebuild',{method:'POST',body:JSON.stringify(p)}),
 indexTask:(id:string|number)=>mock?m(fixtures.admin.indexTask):request(`/api/admin/index/tasks/${id}`),
 // —— 途径与规则维护（admin/pathways.py）——
 adminPathways:(q:any={})=>mock?m(fixtures.admin.pathways):request(`/api/admin/pathways${qs(q)}`),
 savePathway:(p:any)=>mock?m(p):request('/api/admin/pathways',{method:'POST',body:JSON.stringify(p)}),
 // 后端返回 {items:[...]}（非裸数组）；支持 pathway_id/province/rule_type 过滤
 rules:(q:any={})=>mock?m({items:fixtures.admin.pathwayRules}):request(`/api/admin/pathway-rules${qs(q)}`),
 saveRule:(p:any)=>mock?m({rule_id:1}):request('/api/admin/pathway-rules',{method:'POST',body:JSON.stringify(p)}),
 // 兼容旧签名 pathwayRegions(id:string)；真实返回 {items:[region_item]}
 pathwayRegions:(id:string|{pathway_id?:string;province?:string})=>{const q=typeof id==='string'?{pathway_id:id}:id;return mock?m({items:fixtures.admin.regions}):request(`/api/admin/pathway-regions${qs(q)}`)},
 // —— 审核闭环（admin/review.py）：列表默认 pending；动作 approve/correct/reject ——
 reviewTasks:(q:any={})=>mock?m(fixtures.admin.reviewList):request(`/api/admin/review/tasks${qs({status:'pending',...q})}`),
 reviewTask:(id:string|number)=>mock?m(fixtures.admin.reviewDetail):request(`/api/admin/review/tasks/${id}`),
 reviewAction:(id:string|number,p:any)=>mock?m(null):request(`/api/admin/review/tasks/${id}`,{method:'POST',body:JSON.stringify(p)}),
 // 追加接口：扫描问答日志补建待审任务（幂等）。后端注释明言供管理端「刷新」使用，
 // 但契约附录 A 尚未登记该路径 —— 已列入 PR「疑似契约问题待裁决」清单。
 reviewEnqueue:()=>mock?m({scanned:0,enqueued:0}):request('/api/admin/review/enqueue',{method:'POST'}),
 adminStats:()=>mock?m(fixtures.admin.stats):request('/api/admin/stats'),
 // —— 契约 8.8 规则维护：五组规则列表（均分页，支持 province_code/year/batch/data_status 过滤）——
 ruleProvinceRules:(q:any={})=>mock?m(fixtures.admin.ruleProvinceRules):request(`/api/admin/province-rules${qs(q)}`),
 ruleSubjectRequirements:(q:any={})=>mock?m(fixtures.admin.ruleEmpty):request(`/api/admin/subject-requirements${qs(q)}`),
 rulePhysicalRestrictions:(q:any={})=>mock?m(fixtures.admin.ruleEmpty):request(`/api/admin/physical-restrictions${qs(q)}`),
 ruleAdmissionRequirements:(q:any={})=>mock?m(fixtures.admin.ruleEmpty):request(`/api/admin/admission-requirements${qs(q)}`),
 ruleMajorTuitions:(q:any={})=>mock?m(fixtures.admin.ruleEmpty):request(`/api/admin/major-tuition${qs(q)}`),
 // 规则集 data_status（GET/PUT；available 不允许手工设置 → 1001）
 ruleDatasetStatus:(q:any={})=>mock?m(fixtures.admin.ruleDatasetStatus):request(`/api/admin/rule-dataset-status${qs(q)}`),
 // 契约 8.8 批量导入：单次 ≤500 条，整批事务；校验失败整批回滚返回错误包
 importRuleDataset:(p:any)=>mock?m({dataset:p.dataset,created:p.items.length,updated:0,rejected:0,errors:[]}):request('/api/admin/rule-datasets/import',{method:'POST',body:JSON.stringify(p)})
}
const qs=(q:Record<string,any>)=>{const p=new URLSearchParams();Object.entries(q).forEach(([k,v])=>{if(v!==undefined&&v!==null&&v!=='')p.set(k,String(v))});const s=p.toString();return s?`?${s}`:''}
const citeMock={source_name:'演示数据（非官方）',source_url:'https://example.invalid/mock',year:2026}

export { getToken, setToken, clearToken } from './token'

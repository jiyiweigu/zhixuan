import { auth, profile, pathways, eligibility, qa, plans, schools } from '../mocks'
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const useMock = import.meta.env.VITE_USE_MOCK !== 'false'
async function request<T>(path:string, init?:RequestInit):Promise<Zhixuan.ApiResponse<T>> { const r=await fetch(`${API_BASE}${path}`,{...init,headers:{'Content-Type':'application/json',...(init?.headers||{})}}); if(!r.ok) throw new Error(`API ${r.status}`); return r.json() }
const pick=<T>(value:Zhixuan.ApiResponse<T>)=>Promise.resolve(value)
export const api={
 health:()=>request<{status:string}>('/api/health'),
 register:(p:{username:string;password:string})=>useMock?pick(auth.success):request('/api/auth/register',{method:'POST',body:JSON.stringify(p)}),
 login:(p:{username:string;password:string})=>useMock?pick(auth.success):request('/api/auth/login',{method:'POST',body:JSON.stringify(p)}),
 getProfile:()=>useMock?pick(profile.success):request<Zhixuan.Profile>('/api/user/profile'),
 updateProfile:(p:Zhixuan.Profile)=>useMock?pick(profile.success):request('/api/user/profile',{method:'PUT',body:JSON.stringify(p)}),
 pathways:()=>useMock?pick(pathways.success):request<Zhixuan.Pathway[]>('/api/pathways'),
 eligibility:(p:Zhixuan.Profile)=>useMock?pick(eligibility.pending):request<Zhixuan.Eligibility>('/api/pathways/eligibility-check',{method:'POST',body:JSON.stringify(p)}),
 qa:(q:string)=>useMock?pick(qa.success):request<Zhixuan.QaResult>(`/api/qa?q=${encodeURIComponent(q)}`),
 plans:(p:{profile:Zhixuan.Profile;strategy:'冲'|'稳'|'保'})=>useMock?pick(plans.success):request<Zhixuan.PlanResult>('/api/plans',{method:'POST',body:JSON.stringify(p)}),
 schools:(keyword='',province='河南')=>useMock?pick(schools.success):request<Zhixuan.School[]>(`/api/schools?keyword=${encodeURIComponent(keyword)}&province=${encodeURIComponent(province)}`)
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const useMock = import.meta.env.VITE_USE_MOCK !== 'false'
import { mockEligibility, mockQa, mockPathways } from './mock'
async function request<T>(path:string, init?:RequestInit):Promise<Zhixuan.ApiResponse<T>> { const r=await fetch(`${API_BASE}${path}`,{...init,headers:{'Content-Type':'application/json',...(init?.headers||{})}}); if(!r.ok) throw new Error(`API ${r.status}`); return r.json() }
export const api = { health:()=>request<{status:string}>('/api/health'), pathways:()=>useMock?Promise.resolve(mockPathways):request<Zhixuan.Pathway[]>('/api/pathways'), eligibility:(p:Zhixuan.Profile)=>useMock?Promise.resolve(mockEligibility):request<Zhixuan.Eligibility>('/api/pathways/eligibility-check',{method:'POST',body:JSON.stringify(p)}), qa:(q:string)=>useMock?Promise.resolve(mockQa):request<Zhixuan.QaResult>(`/api/qa?q=${encodeURIComponent(q)}`) }

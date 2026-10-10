from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from uuid import uuid4
app=FastAPI(title='智选志愿 API',version='0.1.0')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173'],allow_methods=['*'],allow_headers=['*'])
def ok(data,message='success'): return {'code':0,'message':message,'data':data,'trace_id':str(uuid4())}
class Profile(BaseModel):
    province:str='河南'; score:int; subject_type:str='物理类'
@app.get('/api/health')
def health(): return ok({'status':'ok','service':'zhixuan'})
@app.get('/api/pathways')
def pathways(): return ok([{'id':'special-plan','name':'国家专项计划','status':'待核验','source_name':'教育部阳光高考','source_url':'https://gaokao.chsi.com.cn','year':2026},{'id':'normal-batch','name':'普通批','status':'可查询','source_name':'河南省教育考试院','source_url':'https://www.haeea.cn','year':2026}])
def check(profile): return ok({'eligible':['普通批'],'pending':['国家专项计划'],'profile':profile.model_dump(),'citations':[{'source_name':'河南省教育考试院','source_url':'https://www.haeea.cn','year':2026}]})
@app.post('/api/pathways/eligibility-check')
def guest_eligibility(profile:Profile): return check(profile)
@app.post('/api/eligibility/check')
def eligibility(profile:Profile): return check(profile)
@app.get('/api/qa')
def qa(q:str): return ok({'answer':'请先完善考生档案，我会基于你的省份、分数与选科给出可核验建议。','confidence':0.62,'citations':[{'source_name':'河南省教育考试院','source_url':'https://www.haeea.cn','year':2026}]})

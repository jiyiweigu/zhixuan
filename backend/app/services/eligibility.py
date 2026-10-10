from uuid import uuid4
from app.schemas.core import ProfileRequest
DEMO={'source_name':'演示数据（非官方）','source_url':'https://example.invalid/mock','year':2026}
def response(data, message='success', code=0): return {'code':code,'message':message,'data':data,'trace_id':str(uuid4())}
def build_eligibility(profile): return {'eligible':['普通批'],'pending':['国家专项计划'],'ineligible':[],'profile':profile.model_dump(),'citations':[DEMO]}
def build_plan(profile,strategy): return {'items':[{'school_id':'mock-001','name':'演示院校','province':profile.province,'tier':strategy,'risk_level':'medium',**DEMO}],'risk_notes':['演示数据，仅供开发'],'citations':[DEMO]}

from fastapi import APIRouter
router = APIRouter(prefix='/v1', tags=['v1'])
@router.get('/health')
def health_v1(): return {'code':0,'message':'success','data':{'status':'ok'},'trace_id':'v1'}

from pydantic import BaseModel, Field
class ProfileRequest(BaseModel): province:str='河南'; score:int=Field(ge=0,le=750); subject_type:str='物理类'
class Citation(BaseModel): source_name:str; source_url:str; year:int; index:int|None=None; chunk_id:str|None=None; snippet:str|None=None
class Credentials(BaseModel): username:str=Field(min_length=2,max_length=50); password:str=Field(min_length=6,max_length=128)
class PlanRequest(BaseModel): profile:ProfileRequest; strategy:str=Field(pattern='^(冲|稳|保)$')
class QaAskRequest(BaseModel): question:str=Field(min_length=1,max_length=1000); session_id:str|None=None; province:str|None=None; pathway_id:int|None=None

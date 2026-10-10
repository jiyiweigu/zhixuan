from pydantic import BaseModel, Field
class ProfileRequest(BaseModel):
    province: str = '河南'
    score: int = Field(ge=0, le=750)
    subject_type: str = '物理类'
class Citation(BaseModel):
    source_name: str
    source_url: str
    year: int
class QaResponse(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    citations: list[Citation]

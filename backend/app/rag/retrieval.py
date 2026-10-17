"""Small dependency-free retrieval primitives for SQLite development mode."""
from __future__ import annotations
import math
import re
from collections import Counter
from dataclasses import dataclass

@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: int | str
    score: float
    content: str
    metadata: dict

def cosine_similarity(left:list[float], right:list[float]) -> float:
    if len(left)!=len(right): raise ValueError("vector dimensions must match")
    denominator=math.sqrt(sum(x*x for x in left))*math.sqrt(sum(x*x for x in right))
    return 0.0 if denominator==0 else sum(a*b for a,b in zip(left,right))/denominator

def vector_search(query_vector:list[float], chunks:list[dict], top_k:int=10) -> list[RetrievalHit]:
    hits=[]
    for chunk in chunks:
        vector=chunk.get("embedding")
        if vector is None: continue
        hits.append(RetrievalHit(chunk["chunk_id"],cosine_similarity(query_vector,vector),chunk.get("content", ""),chunk.get("metadata",{})))
    return sorted(hits,key=lambda hit:(hit.score,str(hit.chunk_id)),reverse=True)[:top_k]

def _tokens(text:str)->list[str]: return [token for token in re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+",text.lower())]

def bm25_search(query:str, documents:list[dict], top_k:int=10, k1:float=1.5, b:float=.75)->list[RetrievalHit]:
    if not documents:
        return []
    query_tokens=_tokens(query)
    if not query_tokens:
        return []
    tokenized=[_tokens(doc.get("content", "")) for doc in documents]
    avgdl=sum(map(len,tokenized))/max(len(tokenized),1); n=len(documents)

    # 预建 term -> 文档频率（df）倒排，把每个 term 的 df 从 O(n) 降为 O(1)，
    # 避免对每个 query term 反复全量扫描（候选量大时既慢又易触发原生崩溃）。
    df_by_term: dict[str, int] = {}
    for tokens in tokenized:
        for term in set(tokens):
            df_by_term[term] = df_by_term.get(term, 0) + 1

    hits=[]
    for doc,tokens in zip(documents,tokenized):
        counts=Counter(tokens); score=0.0
        for term in query_tokens:
            df=df_by_term.get(term, 0)
            if not df: continue
            idf=math.log(1+(n-df+0.5)/(df+0.5)); tf=counts[term]; dl=len(tokens)
            score += idf*(tf*(k1+1))/(tf+k1*(1-b+b*dl/max(avgdl,1))) if tf else 0
        hits.append(RetrievalHit(doc["chunk_id"],score,doc.get("content", ""),doc.get("metadata",{})))
    return sorted(hits,key=lambda hit:(hit.score,str(hit.chunk_id)),reverse=True)[:top_k]

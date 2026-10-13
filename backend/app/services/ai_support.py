from uuid import uuid4
from pydantic import BaseModel
DEMO={'source_name':'演示数据（非官方）','source_url':'https://example.invalid/mock','year':2026}
def response(data,message='success',code=0): return {'code':code,'message':message,'data':data,'trace_id':str(uuid4())}
def analyze_trend(points,target_type='school_major'):
    valid=sorted([p for p in points if p.get('year') and p.get('min_rank') and p.get('source_name') and p.get('source_url')],key=lambda p:p['year'])
    years=[p['year'] for p in valid]
    base={'target_type':target_type,'years':years,'points':valid,'disclaimer':'该结果不代表今年实际报名人数、录取概率或录取结果。','citations':[{'source_name':p['source_name'],'source_url':p['source_url'],'year':p['year']} for p in valid]}
    if len(valid)<2 or len(years)!=len(set(years)): return {'trend':'insufficient_data','label':'趋势暂不可判断','confidence':'low','explanation':'历史数据不足或年份口径不可比。',**base}
    change=(valid[-1]['min_rank']-valid[0]['min_rank'])/valid[0]['min_rank']; trend='rising' if change < -.05 else 'falling' if change > .05 else 'stable'; labels={'rising':'竞争热度上升','falling':'竞争热度下降','stable':'竞争热度稳定'}
    return {'trend':trend,'label':labels[trend],'confidence':'high' if len(valid)>=3 else 'medium','explanation':f"近{len(valid)}年最低录取位次由 {valid[0]['min_rank']} 变为 {valid[-1]['min_rank']}，仅作历史趋势研判。",**base}
def restricted_answer(question,snippets):
    if not snippets: return {'answer':'知识库暂无相关数据，建议查阅各省教育考试院官方渠道','confidence':'low','needs_review':True,'degraded':False,'citations':[]}
    citations=[dict(s,index=i+1) for i,s in enumerate(snippets) if s.get('source_name') and s.get('source_url') and s.get('year')]
    if not citations: return restricted_answer(question,[])
    return {'answer':'基于检索片段的演示摘要，请结合来源核验。[1]','confidence':'medium','needs_review':False,'degraded':True,'citations':citations}
def safe_explanation(text): return not any(x in text for x in ('保证录取','一定可以','录取概率'))
def classify_confidence(rerank_score, structured_hit):
    if rerank_score >= 0.8 and structured_hit: return 'high'
    if rerank_score >= 0.55 or structured_hit: return 'medium'
    return 'low'
def rewrite_question(question, history):
    if not history or not any(x in question for x in ('它','这个','该校','这所')): return question
    return f"关于{history[-1].get('entity','上一条对象')}，{question}"
def rrf_merge(vector_hits, keyword_hits, limit=20):
    scores={}
    for rank,item in enumerate(vector_hits,1): scores[item['chunk_id']]=scores.get(item['chunk_id'],0)+1/(60+rank)
    for rank,item in enumerate(keyword_hits,1): scores[item['chunk_id']]=scores.get(item['chunk_id'],0)+1/(60+rank)
    by={x['chunk_id']:x for x in vector_hits+keyword_hits}; return [by[k] for k,_ in sorted(scores.items(),key=lambda x:x[1],reverse=True)[:limit]]
def validate_explanation(text, numbers): return safe_explanation(text) and all(str(n) in text for n in numbers)

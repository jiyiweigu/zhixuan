from app.services.ai_support import analyze_trend,restricted_answer,safe_explanation
def test_trend(): assert analyze_trend([{'year':2023,'min_rank':18000,'source_name':'x','source_url':'u'},{'year':2024,'min_rank':15000,'source_name':'x','source_url':'u'}])['trend']=='rising'
def test_insufficient(): assert analyze_trend([{'year':2024,'min_rank':1,'source_name':'x','source_url':'u'}])['trend']=='insufficient_data'
def test_no_evidence(): assert restricted_answer('q',[])['needs_review']
def test_safe(): assert safe_explanation('历史趋势') and not safe_explanation('保证录取')

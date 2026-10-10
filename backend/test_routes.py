from app.main import app

def test_routes():
    paths={r.path for r in app.routes}
    assert '/api/health' in paths
    assert '/api/pathways/eligibility-check' in paths
    assert '/api/qa' in paths

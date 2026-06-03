from fastapi.testclient import TestClient

from web.app import build_app

def test_health_route_returns_ok():
    client = TestClient(build_app())
    
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status":"ok"}
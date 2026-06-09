from fastapi.testclient import TestClient

from app.main import app


def test_health_root_serves_frontend_or_json() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code in {200, 404}


def test_process_router_registered() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json().get("paths", {})
    assert any(path.startswith("/process/") for path in paths)
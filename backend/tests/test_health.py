from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_is_public_and_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_serves_the_frontend_index():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Tidy</title>" in response.text


def test_unknown_path_gets_the_404_page():
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "Not found" in response.text

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from tracemap.main import create_app


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as c:
        yield c
    app.state.engine.dispose()


@pytest.fixture
def headers():
    return {"Authorization": "Bearer dev-alice"}


@pytest.fixture
def create_project(client, headers):
    def factory(title="竞品研究"):
        response = client.post("/api/v1/projects", json={"title": title, "goal": "分析产品机会"},
                               headers={**headers, "Idempotency-Key": "create-" + __import__("hashlib").sha256(title.encode()).hexdigest()[:16]})
        assert response.status_code == 201, response.text
        return response.json()
    return factory

"""Linux local-deployment smoke tests.

These complement the domain/API tests with the deployment-level invariants a
machine operator cares about:

* data written by one API process is readable by a fresh process on the same
  SQLite file (models a real stop/start, unlike an in-memory TestClient);
* the complete research lifecycle works end to end against a file-backed DB.

Items that cannot be asserted in-process (loopback-only listener, Vite proxy,
Chromium desktop/mobile rendering) live in ``scripts/smoke-test.sh`` and
``apps/web/e2e/`` and are mapped in docs/DEPLOYMENT_LINUX.md.
"""
from fastapi.testclient import TestClient

from tracemap.main import create_app
from test_api import h


def test_file_database_persists_across_api_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'persist.db'}"
    headers = {"Authorization": "Bearer dev-alice"}

    first = create_app(url)
    with TestClient(first) as client:
        created = client.post("/api/v1/projects", json={"title": "持久化研究", "goal": "restart"},
                              headers={**headers, "Idempotency-Key": "persist-create-0001"}).json()
        pid = created["id"]
        added = client.post(f"/api/v1/projects/{pid}/sources/text",
                            json={"title": "材料", "text": "重启后仍可读取。", "format": "text"},
                            headers=h(headers, 0, "persist-source-0001"))
        assert added.status_code == 202
    first.state.engine.dispose()

    # A brand-new app object over the same file models a real service restart.
    second = create_app(url)
    with TestClient(second) as client:
        project = client.get(f"/api/v1/projects/{pid}", headers=headers)
        assert project.status_code == 200, project.text
        assert project.json()["title"] == "持久化研究"
        assert project.json()["revision"] == 1
        sources = client.get(f"/api/v1/projects/{pid}/sources", headers=headers).json()["items"]
        assert len(sources) == 1
    second.state.engine.dispose()


def test_full_research_lifecycle_on_file_database(client, headers, create_project):
    """import text -> generate draft -> user commit -> edit -> undo -> export."""
    pid = create_project("生命周期")["id"]
    source = client.post(f"/api/v1/projects/{pid}/sources/text",
                         json={"title": "访谈", "text": "😀证据先行。\n\n第二段资料。", "format": "text"},
                         headers=h(headers, 0, "life-source-0001"))
    assert source.status_code == 202
    sid = source.json()["sourceId"]

    generated = client.post(f"/api/v1/projects/{pid}/generate",
                            json={"goal": "证据研究", "sourceIds": [sid], "language": "zh-CN"},
                            headers=h(headers, 1, "life-generate-0001"))
    assert generated.status_code == 202, generated.text
    did = generated.json()["draftId"]

    committed = client.post(f"/api/v1/projects/{pid}/generation-drafts/{did}/commit",
                            headers=h(headers, 1, "life-commit-0001"))
    assert committed.status_code == 200, committed.text
    assert committed.json()["revision"] == 2

    target = client.get(f"/api/v1/projects/{pid}/map", headers=headers).json()["nodes"][-1]["id"]
    renamed = client.post(f"/api/v1/projects/{pid}/nodes/ops",
                          json={"operations": [{"op": "rename", "nodeId": target, "title": "人工修订"}]},
                          headers=h(headers, 2, "life-rename-0001"))
    assert renamed.status_code == 200 and renamed.json()["revision"] == 3

    undone = client.post(f"/api/v1/projects/{pid}/undo", headers=h(headers, 3, "life-undo-0001"))
    assert undone.status_code == 200 and undone.json()["revision"] == 4

    markdown = client.get(f"/api/v1/projects/{pid}/export", params={"format": "md"}, headers=headers)
    assert markdown.status_code == 200 and markdown.text.startswith("<!-- TraceMap:")
    document = client.get(f"/api/v1/projects/{pid}/export", params={"format": "json"}, headers=headers).json()
    assert document["revision"] == 4
    assert document["map"]["nodes"]

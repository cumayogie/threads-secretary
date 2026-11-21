import importlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "secretary.db"))
    monkeypatch.setenv("THREADS_PUBLISH_ENABLED", "false")
    monkeypatch.setenv("SECRET_API_KEY", "test-secret-not-for-production")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
    sys.modules.pop("main", None)
    module = importlib.import_module("main")
    module.initialize()
    yield module
    sys.modules.pop("main", None)
    sys.path.pop(0)


def test_health_and_db(app_module):
    with TestClient(app_module.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    with sqlite3.connect(os.environ["DB_PATH"]) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_api_requires_key(app_module):
    with TestClient(app_module.app) as client:
        assert client.get("/drafts").status_code == 401
        assert client.get("/drafts", headers={"x-api-key": "test-secret-not-for-production"}).status_code == 200


def test_approve_and_reject(app_module):
    app_module.app.dependency_overrides[app_module.write_auth] = lambda: {"sub": "test"}
    with app_module.database() as db:
        db.execute("INSERT INTO drafts(topic,content) VALUES('A','A draft')")
        db.execute("INSERT INTO drafts(topic,content) VALUES('B','B draft')")
    with TestClient(app_module.app) as client:
        assert client.post("/ui/drafts/1/approve").status_code == 200
        assert client.post("/ui/drafts/2/reject").status_code == 200
        assert client.post("/ui/drafts/1/approve").status_code == 409
    app_module.app.dependency_overrides.clear()


def test_publish_lock_blocks_api_call(app_module):
    app_module.app.dependency_overrides[app_module.write_auth] = lambda: {"sub": "test"}
    with app_module.database() as db:
        db.execute("INSERT INTO drafts(topic,content,status) VALUES('A','A draft','approved')")
    with TestClient(app_module.app) as client:
        r = client.post("/ui/drafts/1/publish")
        assert r.status_code == 403
    with app_module.database() as db:
        row = db.execute("SELECT publish_state FROM drafts WHERE id=1").fetchone()
        assert row[0] == "not_started"
    app_module.app.dependency_overrides.clear()

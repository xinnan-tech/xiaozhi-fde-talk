"""/health + /ready 探针。

/ready 只查 DB（SELECT 1）：探针被编排器高频轮询，绝不能挂真实
LLM/ASR 调用（烧额度 + 占 ASR 并发 + 失败路径向未认证方回显 provider
细节）。深度诊断在 admin 专用的 POST /api/v1/diagnostics。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.transport.health import mount


def test_health_and_ready_routes_exist():
    app = FastAPI()
    mount(app)
    paths = {r.path for r in app.routes}
    assert "/health" in paths
    assert "/ready" in paths


def _mock_engine(monkeypatch, *, raises: bool = False) -> None:
    import app.persistence.db as dbmod

    ctx = AsyncMock()
    if raises:
        ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("db down"))
        ctx.__aexit__ = AsyncMock(return_value=None)
    else:
        conn = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
    engine = MagicMock()
    engine.connect = MagicMock(return_value=ctx)
    monkeypatch.setattr(dbmod, "engine", engine)


def test_ready_200_when_db_up(monkeypatch):
    _mock_engine(monkeypatch)
    app = FastAPI()
    mount(app)
    with TestClient(app) as client:
        r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["db"] is True


def test_ready_503_when_db_down(monkeypatch):
    _mock_engine(monkeypatch, raises=True)
    app = FastAPI()
    mount(app)
    with TestClient(app) as client:
        r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["ok"] is False

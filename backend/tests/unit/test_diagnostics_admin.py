"""单元测试：diagnostics 端点收紧 admin + 去重尾斜杠路由。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user
from app.transport.http.routes import diagnostics as d


def test_routes_depend_on_require_admin():
    """三个诊断路由的依赖必须是 require_admin（非 get_current_user）。"""
    for route in d.router.routes:
        deps = [str(di.call) for di in route.dependant.dependencies]
        joined = " ".join(deps)
        assert "require_admin" in joined, f"{route.path} 未用 require_admin"


def test_no_duplicate_trailing_slash_routes():
    """不应同时存在 a 与 a/ 两个路由（无尾斜杠、且 rstrip 后唯一）。"""
    paths = [r.path for r in d.router.routes]
    assert all(not p.endswith("/") for p in paths), paths
    assert len(paths) == len({p.rstrip("/") for p in paths}), paths


@pytest.fixture
def diag_client(en_locale):
    """TestClient with get_current_user overridden to a fake admin user, so
    auth-protected diagnostics routes return early with a localized result
    (no real LLM/ASR service required for the i18n assertion)."""
    from app.app import create_app

    app = create_app()

    async def _fake_user() -> CurrentUser:
        return CurrentUser(user_id="diag-test-user", username="admin", role="admin")

    app.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app)


def test_diagnostics_response_is_localized(diag_client):
    """诊断响应应携带 i18n_key 与 Content-Language 头。

    diagnostics 默认从 config_store 读 ws_url / base_url，cache 为空时直接走
    config_missing → 返回结构稳定，含 i18n_key。
    """
    r = diag_client.post("/api/v1/diagnostics/asr", headers={"Accept-Language": "en-US"})
    assert r.status_code == 200
    body = r.json()
    if body.get("code") not in {"ok"}:
        assert "i18n_key" in body, body
        assert body["i18n_key"].startswith("diag."), body
    assert r.headers.get("Content-Language") == "en-US"

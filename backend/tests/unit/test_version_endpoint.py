"""单元测试：GET /api/v1/version —— about 页用的后端版本号。

契约：
- 路径：GET /api/v1/version
- 鉴权：get_current_user（任意登录用户可见，非 admin-only；
  但 about 页本身在白名单、未登录访客请求会 401 → 前端降级显示 "—"）
- 响应：{"version": "0.1.0"}（与 app.__version__ 对齐）
- 依赖必须是 get_current_user 而非 require_admin：
  暴露面比 diagnostics 大一圈（烧额度的重操作才锁 admin，单纯读版本号不需要）
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user
from app.transport.http.routes import version as v


def test_version_route_mounted():
    """版本路由必须挂载在 /api/v1 下（顶层路由器的 prefix）。"""
    paths = {r.path for r in v.router.routes}
    assert "/version" in paths, paths


def test_version_route_depends_on_get_current_user():
    """版本路由的依赖必须是 get_current_user（非 require_admin）。"""
    for route in v.router.routes:
        deps = [str(di.call) for di in route.dependant.dependencies]
        joined = " ".join(deps)
        assert "get_current_user" in joined, f"{route.path} 未用 get_current_user"
        assert "require_admin" not in joined, f"{route.path} 不应锁 admin"


def test_version_no_trailing_slash_route():
    """不应同时存在 a 与 a/ 两个路由（无尾斜杠、且 rstrip 后唯一）。"""
    paths = [r.path for r in v.router.routes]
    assert all(not p.endswith("/") for p in paths), paths
    assert len(paths) == len({p.rstrip("/") for p in paths}), paths


@pytest.fixture
def version_client():
    """TestClient + get_current_user override：模拟任意登录用户。"""
    from app.app import create_app

    app = create_app()

    async def _fake_user() -> CurrentUser:
        # role 用普通用户，与 admin-only 的诊断端点形成对比
        return CurrentUser(user_id="u1", username="user", role="user")

    app.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app)


def test_version_requires_login(version_client):
    """去掉 auth override：未登录 → 401。"""
    # 拿到一个干净的 client（不预装 override）
    from app.app import create_app

    app = create_app()
    client = TestClient(app)
    r = client.get("/api/v1/version")
    assert r.status_code == 401


def test_version_returns_app_version(version_client):
    """任意登录用户 → 200 + {"version": app.__version__}。"""
    r = version_client.get("/api/v1/version")
    assert r.status_code == 200
    assert r.json() == {"version": __version__}
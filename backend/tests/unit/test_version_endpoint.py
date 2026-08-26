"""单元测试：GET /api/v1/version —— about 页用的后端版本号。

契约：
- 路径：GET /api/v1/version
- 鉴权：get_current_user_optional（匿名返 200 + {"version": ""}，登录返
  真实版本号；不放 require_admin，因版本号不是烧额度的重操作）
- 响应：登录 → {"version": app.__version__}；匿名 → {"version": ""}
- 匿名可访问让 about 页在未登录时不再触发"登录状态已过期"toast（issue #77）
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import (
    get_current_user,
    get_current_user_optional,
)
from app.transport.http.routes import version as v


def test_version_route_mounted():
    """版本路由必须挂载在 /api/v1 下（顶层路由器的 prefix）。"""
    paths = {r.path for r in v.router.routes}
    assert "/version" in paths, paths


def test_version_route_depends_on_get_current_user_optional():
    """版本路由的依赖必须是 get_current_user_optional，不应要求强鉴权。"""
    for route in v.router.routes:
        deps = [str(di.call) for di in route.dependant.dependencies]
        joined = " ".join(deps)
        assert "get_current_user_optional" in joined, (
            f"{route.path} 未用 get_current_user_optional，匿名访问会触发 401"
        )
        assert "require_admin" not in joined, f"{route.path} 不应锁 admin"


def test_version_no_trailing_slash_route():
    """不应同时存在 a 与 a/ 两个路由（无尾斜杠、且 rstrip 后唯一）。"""
    paths = [r.path for r in v.router.routes]
    assert all(not p.endswith("/") for p in paths), paths
    assert len(paths) == len({p.rstrip("/") for p in paths}), paths


def test_get_current_user_optional_returns_none_without_token():
    """get_current_user_optional：无 token 时返 None，不抛 401。"""
    from app.transport.http.dependencies import get_current_user_optional

    # 直接调用依赖函数（传 None 模拟 HTTPBearer 提取结果）
    import asyncio

    assert asyncio.run(get_current_user_optional(None)) is None


@pytest.fixture
def version_client():
    """TestClient + get_current_user_optional override：模拟任意登录用户。

    路由直接依赖 get_current_user_optional，必须覆写它；只覆 get_current_user
    路由读到的还是原始 optional 函数，仍返 None。
    """
    from app.app import create_app

    app = create_app()

    async def _fake_user() -> CurrentUser:
        # role 用普通用户，与 admin-only 的诊断端点形成对比
        return CurrentUser(user_id="u1", username="user", role="user")

    app.dependency_overrides[get_current_user_optional] = _fake_user
    return TestClient(app)


def test_version_anonymous_returns_empty(version_client):
    """去掉 auth override：匿名 → 200 + {"version": ""}，不再 401。

    about 页在路由白名单，未登录访客请求不该触发登录过期 toast。"""
    from app.app import create_app

    app = create_app()
    client = TestClient(app)
    r = client.get("/api/v1/version")
    assert r.status_code == 200
    assert r.json() == {"version": ""}


def test_version_returns_app_version(version_client):
    """任意登录用户 → 200 + {"version": app.__version__}。"""
    r = version_client.get("/api/v1/version")
    assert r.status_code == 200
    assert r.json() == {"version": __version__}
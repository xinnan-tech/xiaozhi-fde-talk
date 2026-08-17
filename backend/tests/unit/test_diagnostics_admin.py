"""单元测试：diagnostics 端点收紧 admin + 去重尾斜杠路由。"""
from __future__ import annotations
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

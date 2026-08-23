"""POST /auth/register 限流回归：capacity=3，第 4 次同 (ip, username) → 429。

与 login 限流同款（test_login_rate_limit.py），覆盖注册端点独立的 RateLimiter
实例。桶与登录桶分离——注册更严（capacity=3, refill_per_hour=60），登录
capacity=5。reset 走模块级 _reset_for_test（settings.env=="test" 守门）。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.transport.http.routes import auth as auth_route


@pytest.fixture(autouse=True)
def _reset_limiters():
    """用例间清空两个桶，模块级 RateLimiter 不重置就跨用例累加污染。"""
    auth_route._reset_for_test()
    yield
    auth_route._reset_for_test()


def _req_and_request(username: str = "attacker"):
    """构造 register 路由所需的 Request/DB mock。

    username ≥4 位（RegisterRequest 正则 ^[A-Za-z0-9_-]{4,32}$），否则
    pydantic 校验会先于限流抛 422。MagicMock 让 _client_ip(request) 走
    request.client.host 分支返回 '1.2.3.4'（非 x-forwarded-for 路径）。
    """
    req = MagicMock()
    req.username = username
    req.password = "StrongP@ssW0rd"
    req.confirm_password = "StrongP@ssW0rd"
    request = MagicMock()
    request.headers.get = lambda k: None
    request.client.host = "1.2.3.4"
    return req, request


async def test_register_allows_burst_then_returns_429():
    """capacity=3：前 3 次放行（走 svc_register 后失败），第 4 次 429。"""
    rl = auth_route._register_limiter

    # svc_register 直接抛 I18nError，绕过实际 DB 写入；只验证限流开关生效。
    async def fake_svc_register(db, u, p):
        from app.core.i18n.errors import I18nError
        raise I18nError("dummy", http_status=500)

    import app.transport.http.routes.auth as auth_module
    original_svc = auth_module.svc_register
    auth_module.svc_register = fake_svc_register
    try:
        for _ in range(rl.capacity):
            req, request = _req_and_request()
            with pytest.raises(Exception) as ei:
                await auth_route.register(req, request, db=MagicMock())
            # 失败路径走完限流，状态码应是 500（I18nError 伪造）而不是 429
            assert getattr(ei.value, "http_status", None) != 429
        # 第 4 次：限流先于 svc_register → 429
        req, request = _req_and_request()
        with pytest.raises(Exception) as ei:
            await auth_route.register(req, request, db=MagicMock())
        assert getattr(ei.value, "http_status", None) == 429
    finally:
        auth_module.svc_register = original_svc


async def test_register_limiter_separate_buckets_per_username():
    """不同 username 各自独立桶：第 4 次同 username 才 429，换 username 又放行。

    防止桶复用错配（把同 ip 不同 username 共用导致合法用户互相牵连 429）。
    """
    rl = auth_route._register_limiter

    async def fake_svc_register(db, u, p):
        from app.core.i18n.errors import I18nError
        raise I18nError("dummy", http_status=500)

    import app.transport.http.routes.auth as auth_module
    original_svc = auth_module.svc_register
    auth_module.svc_register = fake_svc_register
    try:
        # 把 username "alice" 桶打满
        for _ in range(rl.capacity):
            req, request = _req_and_request("alice")
            with pytest.raises(Exception):
                await auth_route.register(req, request, db=MagicMock())
        # "alice" 第 4 次：429
        req, request = _req_and_request("alice")
        with pytest.raises(Exception) as ei:
            await auth_route.register(req, request, db=MagicMock())
        assert getattr(ei.value, "http_status", None) == 429
        # "bob" 全新桶：放行
        req, request = _req_and_request("bob")
        with pytest.raises(Exception) as ei:
            await auth_route.register(req, request, db=MagicMock())
        assert getattr(ei.value, "http_status", None) != 429
    finally:
        auth_module.svc_register = original_svc


async def test_register_limiter_and_login_limiter_are_independent():
    """注册桶满不应影响 login 桶：两个 RateLimiter 实例互不干扰。

    同一 ip+username 同时受两个桶保护是设计意图（注册更严），但底层实例必须
    隔离——注册桶清空不该把 login 桶一起清空，反之亦然。注册桶打满后调 login：
    login 应照常 401（认证失败）而不是 429（限流），证明 login 桶未受注册桶污染。
    """
    # 注册桶打满
    rl_reg = auth_route._register_limiter
    for _ in range(rl_reg.capacity):
        req, request = _req_and_request()
        try:
            await auth_route.register(req, request, db=MagicMock())
        except Exception:
            pass
    # login 桶应仍是初始满状态：随便试一次 login 应该不撞 429
    login_req = MagicMock()
    login_req.username = "anyone"
    login_req.password = "x"

    async def fake_auth(db, u, p):
        return None  # 401 路径，绕过 DB

    import app.transport.http.routes.auth as auth_module
    original_auth = auth_module.authenticate_user
    auth_module.authenticate_user = fake_auth
    try:
        with pytest.raises(Exception) as ei:
            await auth_route.login(login_req, request, db=MagicMock())
        assert getattr(ei.value, "http_status", None) == 401, (
            f"login 桶不应被注册桶污染，应 401，实际 {getattr(ei.value, 'http_status', None)}"
        )
    finally:
        auth_module.authenticate_user = original_auth
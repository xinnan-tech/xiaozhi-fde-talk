from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.transport.http.routes import auth as auth_route


async def test_login_allows_burst_then_returns_429(monkeypatch):
    """前 capacity 次放行（因认证失败 → 401），第 capacity+1 次被限流 → 429。"""
    rl = auth_route._login_limiter
    rl._buckets.clear()

    async def fake_auth(db, u, p):
        return None

    monkeypatch.setattr(auth_route, "authenticate_user", fake_auth)

    req = MagicMock()
    req.username = "admin"
    request = MagicMock()
    request.client.host = "1.2.3.4"
    db = MagicMock()

    seen: list[int] = []
    for _ in range(rl.capacity):
        with pytest.raises(Exception) as ei:
            await auth_route.login(req, request, db)
        seen.append(getattr(ei.value, "status_code", None))
    assert all(code == 401 for code in seen), f"burst should reach auth (401), got {seen}"

    with pytest.raises(Exception) as ei:
        await auth_route.login(req, request, db)
    assert getattr(ei.value, "status_code", None) == 429

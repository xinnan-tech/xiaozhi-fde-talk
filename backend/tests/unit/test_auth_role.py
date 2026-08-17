from __future__ import annotations
import pytest
from app.domain.auth import CurrentUser
from app.transport.base import extract_auth


def test_current_user_defaults_role_user():
    u = CurrentUser(user_id="u1")
    assert u.role == "user"


async def test_require_admin_rejects_non_admin(monkeypatch):
    """require_admin 对 role != admin 抛 403。"""
    from app.transport.http import dependencies as dep
    non_admin = CurrentUser(user_id="u1", username="bob", role="user")

    # require_admin 是依赖函数，直接以非 admin 调用应抛 HTTPException(403)
    with pytest.raises(Exception) as ei:
        await dep.require_admin(user=non_admin)
    assert getattr(ei.value, "status_code", None) == 403


async def test_require_admin_accepts_admin():
    from app.transport.http import dependencies as dep
    admin = CurrentUser(user_id="u1", username="admin", role="admin")
    out = await dep.require_admin(user=admin)
    assert out.role == "admin"


async def test_extract_auth_reads_role_from_token(monkeypatch):
    """token payload 带 role → extract_auth 回填到 CurrentUser.role。"""
    monkeypatch.setattr(
        "app.transport.base.decode_token",
        lambda _tok: {"sub": "u1", "username": "bob", "role": "admin"},
    )
    u = extract_auth("Bearer x")
    assert u.role == "admin"

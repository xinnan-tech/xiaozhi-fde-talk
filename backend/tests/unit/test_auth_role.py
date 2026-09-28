from __future__ import annotations
import pytest
from app.domain.auth import CurrentUser
from app.transport.base import extract_auth


def test_current_user_defaults_role_user():
    u = CurrentUser(user_id="u1")
    assert u.role == "user"


async def test_require_admin_rejects_non_admin(monkeypatch):
    """require_admin 对 role != admin 抛 I18nError(http.admin.required, 403)。"""
    from app.core.i18n.errors import I18nError
    from app.transport.http import dependencies as dep
    non_admin = CurrentUser(user_id="u1", username="bob", role="user")

    # require_admin 是依赖函数，直接以非 admin 调用应抛 I18nError(http_status=403)
    with pytest.raises(I18nError) as ei:
        await dep.require_admin(user=non_admin)
    assert ei.value.http_status == 403
    assert ei.value.code == "http.admin.required"


async def test_require_admin_accepts_admin():
    from app.transport.http import dependencies as dep
    admin = CurrentUser(user_id="u1", username="admin", role="admin")
    out = await dep.require_admin(user=admin)
    assert out.role == "admin"


async def test_extract_auth_role_from_db_overrides_token_claim(monkeypatch):
    """role/username 真相源是 DB：DB role=user 压过 token claim 的 role=admin。

    降级场景回归：旧 admin token 的 claim 不得保留旧权限——extract_auth
    一律以 get_auth_state 的 DB 快照构造身份。
    """
    from datetime import datetime, timezone

    from app.persistence.repositories import user as user_mod
    from app.persistence.repositories.user import AuthState

    # claim 声称 admin/alice——必须被 DB 的 user/bob 压过
    monkeypatch.setattr(
        "app.transport.base.decode_token",
        lambda _tok: {"sub": "u1", "username": "alice", "role": "admin", "pwd_ver": 1000},
    )
    # pwd_ver 校验：DB 快照时间戳与 claim 一致（不触发 pwd_ver 吊销路径）
    async def fake_state(user_id):
        return AuthState(
            password_changed_at=datetime.fromtimestamp(1000, tz=timezone.utc),
            role="user",
            username="bob",
        )
    monkeypatch.setattr(user_mod.user_repo, "get_auth_state", fake_state)
    u = await extract_auth("Bearer x")
    assert u.role == "user"
    assert u.username == "bob"

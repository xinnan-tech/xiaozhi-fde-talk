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


async def test_refresh_new_access_role_from_db_overrides_old_claim(monkeypatch):
    """降级场景回归：旧 refresh claim role=admin + DB role=user → 新 access role=user。

    refresh 换发的新 access 身份一律取 DB（get_auth_state），不拷旧 payload——
    与 extract_auth 的 claim-不受信约定互为镜像，防止过期权限经 refresh 续期。
    """
    from datetime import datetime, timezone

    from starlette.responses import Response

    from app.persistence.repositories import user as user_mod
    from app.persistence.repositories.user import AuthState
    from app.services.auth.token import decode_token as real_decode
    from app.transport.http.routes import auth as auth_mod

    # 旧 refresh payload：claim 声称 admin/alice——已与 DB 不符的过期身份
    monkeypatch.setattr(
        "app.transport.http.routes.auth.decode_token",
        lambda _tok: {
            "sub": "u1", "username": "alice", "role": "admin",
            "pwd_ver": 1000, "type": "refresh", "jti": "j-test-role-refresh",
        },
    )
    monkeypatch.setattr(
        "app.transport.http.routes.auth.is_refresh_token_revoked",
        lambda _jti: False,
    )
    # DB 快照：真实身份是 user/bob（pwd_ver 与 claim 一致，不触发吊销路径）
    async def fake_state(user_id):
        return AuthState(
            password_changed_at=datetime.fromtimestamp(1000, tz=timezone.utc),
            role="user",
            username="bob",
        )
    monkeypatch.setattr(user_mod.user_repo, "get_auth_state", fake_state)
    # jwt_secret 由 SecretResolver 在 lifespan 注入——单测没跑 lifespan，
    # 补一个值让 create_access_token / decode_token 能真实签发 + 解码。
    from app.core.settings import get_settings
    monkeypatch.setattr(get_settings(), "jwt_secret", "unit-test-secret")

    class FakeRequest:
        """最小请求桩：client=None → _client_ip 返 "unknown"，绕开 XFF 分支。"""

        client = None
        cookies = {"refresh-token": "stale-refresh-token"}

    out = await auth_mod.refresh(FakeRequest(), Response())
    payload = real_decode(out["access_token"])
    assert payload["role"] == "user"        # DB 的 user 压过旧 claim 的 admin
    assert payload["username"] == "bob"
    assert int(payload["pwd_ver"]) == 1000  # pwd_ver 原样保留（吊销对照值不动）

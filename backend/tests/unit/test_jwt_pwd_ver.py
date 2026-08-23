"""JWT pwd_ver claim：签发注入 + 改密即时吊销。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.exceptions import AuthError
from app.persistence.repositories.user import user_repo
from app.services.auth.token import create_access_token, decode_token
from app.transport.base import extract_auth


@pytest.fixture
def fake_jwt_secret(monkeypatch):
    """单测里 jwt_secret 是 None —— patch settings."""
    import app.services.auth.token as token_mod

    monkeypatch.setattr(
        token_mod, "get_settings",
        lambda: SimpleNamespace(jwt_secret="test-secret"),
    )


@pytest.mark.asyncio
async def test_create_access_token_includes_pwd_ver_claim(fake_jwt_secret):
    """create_access_token 必须把 pwd_ver 写入 payload；decode 后能读出。"""
    token = await create_access_token(subject="u-1", pwd_ver=1710000000)
    payload = decode_token(token)
    assert payload["sub"] == "u-1"
    assert payload["pwd_ver"] == 1710000000


@pytest.mark.asyncio
async def test_extract_auth_rejects_stale_pwd_ver(fake_jwt_secret, monkeypatch):
    """token 的 pwd_ver=1000，但 DB password_changed_at 对应 2000 → 视为改密后旧 token 拒收。"""
    token = await create_access_token(subject="u-x", pwd_ver=1000)

    class FakeRepo:
        async def get_pwd_changed_at(self, user_id):
            return datetime.fromtimestamp(2000, tz=timezone.utc)

    monkeypatch.setattr(user_repo, "get_pwd_changed_at", FakeRepo().get_pwd_changed_at)

    with pytest.raises(AuthError):
        await extract_auth(token)

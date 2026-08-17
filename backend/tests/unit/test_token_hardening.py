from __future__ import annotations
import pytest
import jwt as pyjwt
from app.services.auth import token as tok


def test_decode_rejects_alg_none(monkeypatch):
    """伪造 alg=none 的 token 必须被拒（decode 用硬白名单，不信任 env 算法）。"""
    settings = type("S", (), {"jwt_secret": "k", "jwt_algorithm": "none"})()
    monkeypatch.setattr(tok, "get_settings", lambda: settings)
    forged = pyjwt.encode({"sub": "u1"}, "", algorithm="none", headers={"alg": "none"})
    with pytest.raises(Exception):
        tok.decode_token(forged)


def test_decode_whitelist_ignores_env_algorithm(monkeypatch):
    """env 把 jwt_algorithm 改成 HS384，decode 仍用硬白名单 ["HS256"] 拒绝。

    伪造 token 带 aud 且签名合法，使「唯一差异」是算法列表：env-driven
    (algorithms=["HS384"]) 会接受（RED），硬白名单 (["HS256"]) 拒绝（GREEN）。
    """
    secret = "k" * 32
    settings = type("S", (), {"jwt_secret": secret, "jwt_algorithm": "HS384"})()
    monkeypatch.setattr(tok, "get_settings", lambda: settings)
    forged = pyjwt.encode(
        {"sub": "u1", "aud": "xiaozhi-client"}, secret, algorithm="HS384",
    )
    with pytest.raises(Exception):
        tok.decode_token(forged)


async def test_token_has_standard_claims(monkeypatch):
    settings = type("S", (), {"jwt_secret": "k" * 32, "jwt_algorithm": "HS256"})()
    monkeypatch.setattr(tok, "get_settings", lambda: settings)
    async def fake_cfg():
        return {"jwt_expire_minutes": 60}
    monkeypatch.setattr(tok, "get_auth_runtime_config", fake_cfg)
    t = await tok.create_access_token(subject="u1", extra={"username": "a", "role": "admin"})
    payload = pyjwt.decode(t, "k" * 32, algorithms=["HS256"], options={"verify_aud": False})
    assert "jti" in payload and "iss" in payload and "aud" in payload


def test_jwt_secret_is_sensitive():
    from app.core.config_store import SENSITIVE_KEYS
    assert "system.jwt_secret" in SENSITIVE_KEYS

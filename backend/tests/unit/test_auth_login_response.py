"""LoginResponse / RefreshResponse schema 形状回归。

access / refresh token 通过 HttpOnly cookie 下发（主路径）；
响应 body 保留 token 字段作兼容路径（scripts / chaos.py / Authorization Bearer 测试）。

前端主路径走 cookie，body token 走脚本与测试。token 字段若意外从 schema 移除
会破坏 ~54 个测试文件。
"""
import pytest
from app.transport.http.schemas import LoginResponse, UserInfo, RefreshResponse


def test_login_response_has_user_and_tokens():
    """LoginResponse 同时含 user + access_token + refresh_token + token_type。
    token 字段是兼容路径，前端不读——前端只读 user。"""
    resp = LoginResponse(
        access_token="a.jwt",
        refresh_token="r.jwt",
        token_type="bearer",
        user=UserInfo(id="u-1", username="alice", role="user"),
    )
    dumped = resp.model_dump()
    assert dumped["user"]["username"] == "alice"
    assert dumped["user"]["id"] == "u-1"
    assert dumped["user"]["role"] == "user"
    assert dumped["access_token"] == "a.jwt"
    assert dumped["refresh_token"] == "r.jwt"
    assert dumped["token_type"] == "bearer"


def test_login_response_default_empty_tokens():
    """token 字段默认空字符串：兼容场景构造（没拿到 token 的 UserInfo 子对象）不报错。"""
    resp = LoginResponse(user=UserInfo(id="u-1", username="bob", role="user"))
    dumped = resp.model_dump()
    assert dumped["access_token"] == ""
    assert dumped["refresh_token"] == ""


def test_refresh_response_has_token_field():
    """RefreshResponse 含 access_token 字段（兼容路径）+ token_type。"""
    fields = set(RefreshResponse.model_fields.keys())
    assert "access_token" in fields, fields
    assert "token_type" in fields, fields
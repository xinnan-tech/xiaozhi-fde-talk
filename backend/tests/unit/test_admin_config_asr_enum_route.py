"""issue #209：PUT /api/v1/admin/config/asr 的 type 字段脏值返 400 + i18n 而不是 500。

旧实现 `_expand_asr` 把 `type` 字段原值写入 `asr.type`，config_store 的
ENUM 校验 `value not in allowed`（set[str]）对 unhashable 类型抛 TypeError，
未捕获一路冒到 FastAPI 默认 handler 转 500；admin 看到 Internal Server
Error 没法定位。修两处：
1. `_expand_asr` 给 `type` 加 str() 兜底，跟内层 str(v) 对齐
2. `config_store.validate_value` 的 ENUM 分支先 isinstance(value, str)
   检查，非字符串统一走 400 + invalid_enum_value

本文件覆盖端到端：list / dict / 空 list / 空 dict → 400 + 结构化 i18n。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config_store import ConfigStore
from app.core.i18n.messages import Keys
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user


@pytest.fixture
def admin_client(monkeypatch):
    """TestClient + admin override + 钉住 ConfigStore 单例到内存实例。"""
    from app.app import create_app

    app = create_app()

    async def _fake_user() -> CurrentUser:
        return CurrentUser(user_id="admin-asr-test", username="admin", role="admin")

    app.dependency_overrides[get_current_user] = _fake_user

    prev_instance = ConfigStore._instance
    ConfigStore._instance = None
    store = ConfigStore()
    store._cache = {"asr.type": "funasr_server"}
    ConfigStore._instance = store

    class _FakeSession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def commit(self):
            pass

        async def execute(self, stmt):
            pass

    monkeypatch.setattr(
        "app.core.config_store.SessionLocal",
        lambda: _FakeSession(),
    )

    try:
        yield TestClient(app), store
    finally:
        ConfigStore._instance = prev_instance


@pytest.mark.parametrize(
    "bad_type",
    [
        ["funasr_server"],
        {"a": "b"},
        [],
        {},
    ],
)
def test_put_asr_type_unhashable_returns_400(admin_client, bad_type):
    """asr.type 传 list / dict / 空 list / 空 dict → 400 + invalid_enum_value。

    旧实现这些都返 500 + Internal Server Error + 服务端 traceback 进日志
    污染。修后跟 type=int / type=null 行为一致：admin 看到结构化 4xx 错因。
    """
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/asr",
        headers={"Accept-Language": "zh-CN"},
        json={"type": bad_type, "funasr_server": {"language": "zh"}},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["code"] == Keys.CONFIG_INVALID_ENUM_VALUE.value, body
    assert "asr.type" in body["detail"], body
    # allowed 字段给出可选枚举值，admin 可直接对账
    assert "funasr_server" in body["detail"], body
    assert "doubao_stream" in body["detail"], body


def test_put_asr_type_int_still_returns_400(admin_client):
    """asr.type=42 行为不变：400 + invalid_enum_value（与新加的 list/dict 一致）。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/asr",
        headers={"Accept-Language": "zh-CN"},
        json={"type": 42, "funasr_server": {"language": "zh"}},
    )
    assert r.status_code == 400, r.text
    assert r.json()["code"] == Keys.CONFIG_INVALID_ENUM_VALUE.value


def test_put_asr_type_valid_string_succeeds(admin_client):
    """asr.type="funasr_server" + 合法 language 仍然 200，证明新校验没误伤正常路径。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/asr",
        json={"type": "funasr_server", "funasr_server": {"language": "zh"}},
    )
    assert r.status_code == 200, r.text

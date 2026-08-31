"""PUT /api/v1/admin/config/coach 数值校验端到端：坏值返 400 而非 500 且含 i18n 文案。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config_store import ConfigStore
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user


@pytest.fixture
def admin_client(monkeypatch):
    """TestClient + admin override + 钉住 ConfigStore 单例到内存实例；yield 后恢复 prev 防污染。"""
    from app.app import create_app

    app = create_app()

    async def _fake_user() -> CurrentUser:
        return CurrentUser(user_id="admin-route-test", username="admin", role="admin")

    app.dependency_overrides[get_current_user] = _fake_user

    # 用一次性内存实例喂给 singleton；teardown 恢复 prev 防止污染同进程后续测试
    prev_instance = ConfigStore._instance
    ConfigStore._instance = None
    store = ConfigStore()
    store._cache = {
        "coach.pause_s": "5.0",
        "coach.max_pending_segments": "8",
        "coach.min_interval_s": "10.0",
        "coach.llm_timeout_s": "45.0",
    }
    ConfigStore._instance = store  # 让 get_config_store() 在请求处理中拿到这一份

    class _FakeSession:
        # set_many 先调 session.bind.dialect.name 走方言分支
        bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def commit(self): pass
        async def execute(self, stmt): pass  # 普通 async 方法返回 None，不连 DB

    monkeypatch.setattr(
        "app.core.config_store.SessionLocal",
        lambda: _FakeSession(),
    )

    try:
        yield TestClient(app), store
    finally:
        ConfigStore._instance = prev_instance


def test_put_coach_negative_float_returns_400(admin_client):
    """pause_s=-1 → 400，detail 含 i18n 文案与字段名，code 稳定。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "zh-CN"},
        json={"pause_s": "-1"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["code"] == "config.invalid_positive_number", body
    assert "正数" in body["detail"], body
    assert "pause_s" in body["detail"] or "coach.pause_s" in body["detail"], body


def test_put_coach_negative_int_returns_400(admin_client):
    """max_pending_segments=-100 → 400，detail 含 '正整数' 与字段名，code 稳定。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "zh-CN"},
        json={"max_pending_segments": "-100"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["code"] == "config.invalid_positive_integer", body
    assert "正整数" in body["detail"], body
    assert (
        "max_pending_segments" in body["detail"]
        or "coach.max_pending_segments" in body["detail"]
    ), body


def test_put_coach_non_numeric_returns_400(admin_client):
    """min_interval_s='abc' → 400，detail 含 i18n 文案与字段名。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "zh-CN"},
        json={"min_interval_s": "abc"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["code"] == "config.invalid_positive_number", body
    assert "正数" in body["detail"], body
    assert (
        "min_interval_s" in body["detail"]
        or "coach.min_interval_s" in body["detail"]
    ), body


def test_put_coach_large_negative_returns_400(admin_client):
    """llm_timeout_s=-9999 → 400，detail 含 i18n 文案与字段名。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "zh-CN"},
        json={"llm_timeout_s": "-9999"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["code"] == "config.invalid_positive_number", body
    assert "正数" in body["detail"], body
    assert (
        "llm_timeout_s" in body["detail"]
        or "coach.llm_timeout_s" in body["detail"]
    ), body


def test_put_coach_nan_returns_400(admin_client):
    """pause_s='nan' → 400，math.isfinite 兜住浮点特殊值。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "en-US"},
        json={"pause_s": "nan"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["code"] == "config.invalid_positive_number", body
    assert "positive number" in body["detail"].lower(), body
    assert "pause_s" in body["detail"] or "coach.pause_s" in body["detail"], body


def test_put_coach_inf_returns_400(admin_client):
    """pause_s='inf' → 400，detail 含 i18n 文案与字段名。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "en-US"},
        json={"pause_s": "inf"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["code"] == "config.invalid_positive_number", body
    assert "positive number" in body["detail"].lower(), body
    assert "pause_s" in body["detail"] or "coach.pause_s" in body["detail"], body


def test_put_coach_zero_returns_400(admin_client):
    """pause_s='0' → 400，detail 含 i18n 文案与字段名。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "en-US"},
        json={"pause_s": "0"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["code"] == "config.invalid_positive_number", body
    assert "positive number" in body["detail"].lower(), body
    assert "pause_s" in body["detail"] or "coach.pause_s" in body["detail"], body


def test_put_coach_valid_value_succeeds(admin_client):
    """合法值 → 200 且 cache 已同步更新（P1-1 让该断言真正生效）。"""
    client, store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "en-US"},
        json={"pause_s": "7.0"},
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    assert r.json() == {"ok": True, "group": "coach"}
    # _FakeSession.execute 是普通 async 方法返回 None，不连 DB；set_many 在
    # commit 成功后把值写入 cache，所以此处断言 cache 同步是有效校验。
    assert store._cache["coach.pause_s"] == "7.0"

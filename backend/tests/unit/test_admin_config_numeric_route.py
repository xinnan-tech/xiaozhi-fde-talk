"""PUT /api/v1/admin/config/coach 数值校验端到端：返 400 而非 500。

回归 issue #139：原代码 admin 输入 -1 / -100 / abc / -9999 时，整条 PUT 链
（admin_config 路由 → set_many → validate_value）里 int(value)/float(value)
裸抛 ValueError；FastAPI 默认未处理异常处理器把它翻成 500 Internal Server
Error，前端 toast 只显示一行没用的英文。

修复后：validate_value 把 ValueError 转成 I18nError(http_status=400)；
I18nError exception handler（app.py:257）按 locale 返 JSON {detail, code}。
本测试断言：每种坏值都拿到 400 而非 500，response 含 i18n 友好的 detail
和 config.invalid_positive_integer/number 这种结构化 code。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.config_store import ConfigStore
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user


@pytest.fixture
def admin_client(monkeypatch):
    """TestClient + admin 角色 override + mock ConfigStore.set_many。

    set_many 直接桩成真实 ConfigStore.set_many，但底层 SessionLocal 不连库——
    我们用 in-memory 缓存代替：写入校验失败时异常先于任何 SQL 抛出，断言路径
    不需要真实 DB；写成功路径只验证 cache 更新（暖调用一次 warm() 即可）。
    """
    from app.app import create_app

    app = create_app()

    async def _fake_user() -> CurrentUser:
        return CurrentUser(user_id="admin-route-test", username="admin", role="admin")

    app.dependency_overrides[get_current_user] = _fake_user

    # 让 ConfigStore 用一个独立的内存实例，避免污染全局 singleton 缓存
    ConfigStore._instance = None
    store = ConfigStore()
    store._cache = {
        "coach.pause_s": "5.0",
        "coach.max_pending_segments": "8",
        "coach.min_interval_s": "10.0",
        "coach.llm_timeout_s": "45.0",
    }

    class _FakeSession:
        # set_many 先调 session.bind.dialect.name 走方言分支
        bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def commit(self): pass
        async def execute(self, stmt): pass

    monkeypatch.setattr(
        "app.core.config_store.SessionLocal",
        lambda: _FakeSession(),
    )

    return TestClient(app), store


def test_put_coach_negative_float_returns_400(admin_client):
    """pause_s=-1 → 400 (非 500)，detail 含本地化 '正数' 文案与字段名。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "zh-CN"},
        json={"pause_s": "-1"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert "detail" in body, body
    assert "正数" in body["detail"], body
    assert "pause_s" in body["detail"] or "coach.pause_s" in body["detail"], body


def test_put_coach_negative_int_returns_400(admin_client):
    """max_pending_segments=-100 → 400，detail 含 '正整数' 与字段名。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "zh-CN"},
        json={"max_pending_segments": "-100"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert "正整数" in body["detail"], body


def test_put_coach_non_numeric_returns_400(admin_client):
    """min_interval_s='abc' → 400（int('abc')/float('abc') 抛 ValueError 已被兜住）。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "zh-CN"},
        json={"min_interval_s": "abc"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert "正数" in body["detail"], body


def test_put_coach_large_negative_returns_400(admin_client):
    """llm_timeout_s=-9999 → 400（极端负数）。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "zh-CN"},
        json={"llm_timeout_s": "-9999"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


def test_put_coach_nan_returns_400(admin_client):
    """pause_s='nan' → 400（math.isfinite 兜住浮点特殊值）。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "en-US"},
        json={"pause_s": "nan"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    body = r.json()
    assert "positive number" in body["detail"].lower(), body


def test_put_coach_inf_returns_400(admin_client):
    """pause_s='inf' → 400。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "en-US"},
        json={"pause_s": "inf"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


def test_put_coach_zero_returns_400(admin_client):
    """0 也被 v<=0 兜住 → 400。"""
    client, _store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "en-US"},
        json={"pause_s": "0"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


def test_put_coach_valid_value_succeeds(admin_client):
    """合法值 → 200（兜底：别因为新增校验把好路径也挡了）。"""
    client, store = admin_client
    r = client.put(
        "/api/v1/admin/config/coach",
        headers={"Accept-Language": "en-US"},
        json={"pause_s": "7.0"},
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    assert r.json() == {"ok": True, "group": "coach"}
    # cache 已更新（_FakeSession 不连 DB，但 cache 由 set_many 在 SQL 成功后写入）
    # 这里因为 _FakeSession.execute 是 AsyncMock 默认返 Mock 对象，upsert 路径会
    # 抛 AttributeError；用合法路径只断言 status 即可—— cache 同步是 _FakeSession
    # 的事，单测不验证 DB 落库由集成测试负责。

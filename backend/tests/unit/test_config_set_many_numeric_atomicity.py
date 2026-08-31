"""set_many 数值校验原子性：列表里任一项校验失败 → 整批不 commit、不污染 cache。

回归 issue #139：原代码 admin 输 `-1 / -100 / abc / -9999` 这一串坏值时，
set_many 一边循环一边调 validate_value；坏值抛 ValueError/I18nError 之前
好的几项已经 execute 过 SQL，但 commit 是在 for 循环跑完才统一调——靠 session
上下文退出时不 commit 触发 SQLAlchemy 自动回滚，所以即便 execute 已经下发，
只要没 commit 就不会落库。

本测试断言"部分写入"的兜底——commit 是真正的事务闸门，不是 execute：
- 坏值在第 2/4/N 项：前几项 execute 可触发（无害，未 commit 不落库），但
  commit 必须 0 次、cache 必须无任何更新、订阅者必须没收到通知
- 坏值在第 1 项：execute 0 次（for 循环第一轮就炸）
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config_store import ConfigStore


@pytest.fixture
def store():
    ConfigStore._instance = None
    s = ConfigStore()
    # 初始 cache：模拟落库过的默认值；用于事后断言坏值未污染 cache
    s._cache = {
        "coach.pause_s": "5.0",
        "coach.max_pending_segments": "8",
        "coach.min_interval_s": "10.0",
        "coach.llm_timeout_s": "45.0",
    }
    return s


@pytest.mark.asyncio
async def test_set_many_one_bad_numeric_aborts_at_commit(store, monkeypatch):
    """3 项合法 + 第 4 项坏值（float 字段写 'abc'）：commit 不发生、cache 不动。"""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    session.execute = AsyncMock()

    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    notified: list = []

    def _on_change(ks):  # noqa: ARG001
        notified.append(ks)

    store.subscribe(_on_change)

    with pytest.raises(Exception):  # I18nError；具体 type 由 i18n 模块兜住
        await store.set_many({
            "coach.pause_s": "8.0",
            "coach.max_pending_segments": "10",
            "coach.min_interval_s": "15.0",
            "coach.llm_timeout_s": "abc",  # 坏值 → I18nError
        })

    # 真闸门：commit 必须 0 次——即便前 3 项 execute 过，没 commit SQLAlchemy 必回滚
    session.commit.assert_not_called()
    # cache 一项都没变（set_many 在 commit 成功前不动 cache）
    assert store._cache["coach.pause_s"] == "5.0"
    assert store._cache["coach.max_pending_segments"] == "8"
    assert store._cache["coach.min_interval_s"] == "10.0"
    assert store._cache["coach.llm_timeout_s"] == "45.0"
    # 订阅者没收到通知——保证调用方拿不到"半成功"事件
    assert notified == []


@pytest.mark.asyncio
async def test_set_many_bad_first_item_blocks_all_execute(store, monkeypatch):
    """坏值在第 1 项：execute 0 次、commit 0 次（for 循环第一轮就炸）。"""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    session.execute = AsyncMock()

    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    with pytest.raises(Exception):
        await store.set_many({
            "coach.pause_s": "abc",  # 第一项就炸
            "coach.llm_timeout_s": "45.0",
        })

    session.execute.assert_not_called()
    session.commit.assert_not_called()
    assert store._cache["coach.pause_s"] == "5.0"
    assert store._cache["coach.llm_timeout_s"] == "45.0"


@pytest.mark.asyncio
async def test_set_many_negative_int_aborts_at_commit(store, monkeypatch):
    """负数 int（max_pending_segments=-100）：commit 不发生。"""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    session.execute = AsyncMock()

    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    with pytest.raises(Exception):
        await store.set_many({
            "coach.pause_s": "8.0",
            "coach.max_pending_segments": "-100",  # 负数炸
        })

    session.commit.assert_not_called()
    assert store._cache["coach.pause_s"] == "5.0"


@pytest.mark.asyncio
async def test_set_many_nan_aborts_at_commit(store, monkeypatch):
    """NaN float：math.isfinite 拦截 → commit 不发生。"""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    session.execute = AsyncMock()

    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)

    with pytest.raises(Exception):
        await store.set_many({
            "coach.pause_s": "nan",  # math.isfinite 兜住
        })

    session.commit.assert_not_called()
    assert store._cache["coach.pause_s"] == "5.0"

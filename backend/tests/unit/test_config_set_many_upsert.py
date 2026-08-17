"""P2-14b · ConfigStore.set_many 用方言级 upsert 取代 get-then-add。

L5：set_many 对缺失 key 先 session.get→None 再 session.add；并发两次写同一缺失 key
都读到 None 都 add，commit 时第二个撞 PK 冲突（IntegrityError）。改为单条
INSERT ... ON CONFLICT DO UPDATE（方言适配），原子且无竞态。

判定：桩 SessionLocal，session.get 返 None（模拟缺失 key），捕获 execute 的语句。
- 当前代码：get 桩不经 execute、add 不经 execute → captured 空，且 add 被调用（红）
- 修复后：执行 INSERT ON CONFLICT DO UPDATE → captured 非空，add 不被调用（绿）
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import sqlite as sqlite_dialect

from app.core import config_store as cs_module
from app.core.config_store import ConfigStore


@pytest.fixture
def store():
    ConfigStore._instance = None
    return ConfigStore()


@pytest.mark.asyncio
async def test_set_many_uses_upsert_statement(store, monkeypatch):
    captured: list = []

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.get = AsyncMock(return_value=None)  # 模拟 key 不存在
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def _exec(stmt):
        captured.append(stmt)

    session.execute = AsyncMock(side_effect=_exec)
    monkeypatch.setattr(cs_module, "SessionLocal", lambda: session)

    await store.set_many({"coach.pause_s": "7"})

    assert captured, "set_many 未执行任何 SQL（get-then-add 不会产生 execute）"
    sql = str(captured[0].compile(dialect=sqlite_dialect.dialect())).lower()
    assert "insert" in sql and "conflict" in sql and "update" in sql, (
        f"set_many 应走 INSERT ON CONFLICT DO UPDATE，实际：{sql}"
    )
    session.add.assert_not_called()  # upsert 不走 ORM add

"""P2-3 · engine 每次现取 LLM，避免持有 admin 改配置后已 aclose 的旧实例。

admin 改 llm.base_url → factory.invalidate aclose 旧 provider → get_llm 返回新 provider。
若 engine 缓存 ainit 时的实例，重算会用到已关闭的 client。_llm_with_timeout 是获取
LLM provider 的唯一入口（_recompute / _final_recompute 都经它），改为经 _get_llm()
现取即可覆盖两条重算路径。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.coaching.engine import CoachingEngine


@pytest.mark.asyncio
async def test_llm_with_timeout_fetches_provider_fresh(make_state):
    """_llm_with_timeout 必须经 _get_llm() 现取 provider，不用 ainit 缓存的旧实例。"""
    engine = CoachingEngine(make_state(), lambda m: None)

    stale = MagicMock()
    stale.chat_json = AsyncMock(return_value={"stale": True})
    fresh = MagicMock()
    fresh.chat_json = AsyncMock(return_value={"items": []})
    engine._llm = stale  # 模拟 ainit 缓存的旧实例

    calls: list[int] = []

    def _fresh():
        calls.append(1)
        return fresh

    engine._get_llm = _fresh  # 生产里 _get_llm 返回 get_llm()

    result = await engine._llm_with_timeout("sys", "user")

    assert len(calls) == 1, "_llm_with_timeout 必须经 _get_llm() 现取 provider"
    fresh.chat_json.assert_awaited_once()
    stale.chat_json.assert_not_called()  # 不得使用 ainit 缓存的旧实例
    assert result == {"items": []}

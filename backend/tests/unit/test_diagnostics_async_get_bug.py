"""diagnose_asr 同步读取 asr.sample_rate（不能 await）。

P3-10 重构时漏改：diagnose_asr 把 cfg.get("asr.ws_url") 改成了 get_sync，
但同行的 cfg.get("asr.sample_rate") 没改 —— 调用方是同步上下文（不 await），
导致 int(coroutine) TypeError → 500。
"""
from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

from app.services import diagnostics


def test_diagnose_asr_uses_get_sync_not_async_get():
    """源码层面：diagnose_asr 不应在同步上下文调 cfg.get（async 方法）必须 await。"""
    src = inspect.getsource(diagnostics.diagnose_asr)
    assert "cfg.get(\"asr" not in src, (
        "diagnose_asr 仍在调 cfg.get()（async，未 await 会变 coroutine）。"
        "P3-10 重构漏改——必须改用 cfg.get_sync()。"
    )


@pytest.mark.asyncio
async def test_diagnose_asr_short_circuits_on_missing_ws_url():
    """ws_url 缺失 → 直接返回 config_missing，不进 FunASR 调用栈。"""
    with patch.object(diagnostics, "get_config_store") as gcs:
        gcs.return_value.get_sync = lambda key, default=None: ""
        res = await diagnostics.diagnose_asr()
    assert res["code"] == "config_missing"


@pytest.mark.asyncio
async def test_diagnose_asr_parses_sample_rate_as_int():
    """sample_rate 是字符串 "16000" → 必须被解析为 int 16000（不能是 coroutine）。

    之前的 bug：cfg.get("asr.sample_rate") 没 await → coroutine → int(coroutine) 抛 TypeError。
    修复后：cfg.get_sync("asr.sample_rate") → "16000" → int(...) = 16000。

    通过 stub FunASRServerProvider，让诊断走到 _ws.send 时因没有 _ws 抛 AttributeError，
    但 _sample_rate 已被读取——证明 sample_rate 是 int 而非 coroutine。
    """
    captured: dict = {}

    class StubProvider:
        def __init__(self):
            cfg = diagnostics.get_config_store()
            self._ws_url = cfg.get_sync("asr.ws_url") or "wss://localhost:10096"
            self._sample_rate = int(cfg.get_sync("asr.sample_rate") or 16000)
            captured["ws_url"] = self._ws_url
            captured["sample_rate"] = self._sample_rate

        async def start_stream(self, _on_utterance):
            # 不真连 FunASR，立即返回——测试只看 __init__ 后的 _sample_rate
            return None

    with patch.object(diagnostics, "get_config_store") as gcs, \
         patch.object(diagnostics, "FunASRServerProvider", StubProvider):
        gcs.return_value.get_sync = lambda key, default=None: \
            "16000" if "sample_rate" in key else \
            ("wss://localhost:10096" if "ws_url" in key else default)
        # 走到 _ws.send 会 AttributeError，被外层 try/except 捕获 → 返回 error dict，不抛
        res = await diagnostics.diagnose_asr(timeout_s=0.5)
        assert res is not None

    assert captured.get("sample_rate") == 16000, (
        f"sample_rate 应被解析为 int 16000，实际拿到 {captured.get('sample_rate')!r}"
    )
    assert isinstance(captured.get("sample_rate"), int)
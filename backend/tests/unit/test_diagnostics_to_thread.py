"""· diagnose_asr 把 _build_test_audio（重采样 + WAV 编码）offload 到工作线程。

M4：_build_test_audio 是同步 CPU/IO，原在 diagnose_asr 里同步调用，阻塞事件循环。
判定：在 _build_test_audio 内捕获 threading.current_thread()，断言非 main thread。
同步调用 → main thread（红）；asyncio.to_thread → 工作线程（绿）。无计时竞态。
"""
from __future__ import annotations

import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.diagnostics as diag


@pytest.mark.asyncio
async def test_diagnose_asr_offloads_build_audio_to_thread(monkeypatch):
    main_thread = threading.main_thread()
    seen: list[threading.Thread] = []

    def slow_build(sample_rate: int) -> bytes:
        seen.append(threading.current_thread())
        return b"fake-wav"

    monkeypatch.setattr(diag, "_build_test_audio", slow_build)

    # 配置带 ws_url（过 line 211 检查，进入 215 的 _build_test_audio）
    fake_cfg_store = MagicMock()
    fake_cfg_store._cache = {"asr.ws_url": "ws://x", "asr.sample_rate": "16000"}
    monkeypatch.setattr(diag, "get_config_store", lambda: fake_cfg_store)

    # provider：start_stream 立即抛，让 diagnose_asr 早返回、不触网络
    fake_provider = MagicMock()
    fake_provider.start_stream = AsyncMock(side_effect=OSError("no net"))
    fake_provider.close = AsyncMock()
    monkeypatch.setattr(diag, "FunASRServerProvider", lambda: fake_provider)

    await diag.diagnose_asr(timeout_s=2.0)

    assert seen, "_build_test_audio 未被调用"
    assert seen[0] is not main_thread, (
        "_build_test_audio 在事件循环线程执行——diagnose_asr 未用 asyncio.to_thread offload"
    )

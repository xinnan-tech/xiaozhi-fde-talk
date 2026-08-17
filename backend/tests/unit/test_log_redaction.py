from __future__ import annotations

import logging
from unittest.mock import AsyncMock

from app.core.security import redact_text


def test_redact_truncates_long_text():
    long = "这是一段很长的转写文本内容" * 5
    r = redact_text(long, max_chars=10)
    assert not r.endswith(long[-1])  # 不是原文末尾
    assert "…" in r or len(r) < len(long)


async def test_runtime_segment_log_redacted(make_state, caplog):
    """runtime._on_utterance 落日志的 seg.text 必须脱敏（不含原文全文）。"""
    from app.services.sessions.runtime import SessionRuntime

    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt._save_state = AsyncMock()
    long_text = "机密转写内容请勿外泄" * 10
    with caplog.at_level(logging.INFO, logger="app.services.sessions.runtime"):
        await rt._on_utterance(long_text, True, 16000)
    dumped = " ".join(r.getMessage() for r in caplog.records)
    assert long_text not in dumped

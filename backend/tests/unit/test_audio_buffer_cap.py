from __future__ import annotations

from unittest.mock import AsyncMock

from app.adapters.asr.audio_decode import WebMDecoder


def test_decoder_resets_after_cap_without_raising():
    d = WebMDecoder(max_buf_bytes=4000)
    d._decode = lambda data: b""                       # 安全阀触发时不真解 1MB 垃圾
    d.feed(b"\x1a\x45\xdf\xa3" + b"\x00" * 1_000_000)
    out = d.feed(b"\x1a\x45\xdf\xa3" + b"\x00" * 100)
    assert isinstance(out, bytes)
    assert len(d._buf) < 1_000_000  # 安全阀已复位


def test_decoder_exposes_buffer_fields():
    d = WebMDecoder()
    assert hasattr(d, "overflowed")
    assert hasattr(d, "feed")


async def test_pipeline_calls_on_overflow():
    from app.services.sessions.pipeline import AudioPipeline

    class FakeDecoder:
        def __init__(self) -> None:
            self.overflowed = True

        def feed(self, webm: bytes, force: bool = False) -> bytes:
            return b""

    on_overflow = AsyncMock()
    pipe = AudioPipeline(on_utterance=AsyncMock(), on_overflow=on_overflow)
    pipe.decoder = FakeDecoder()
    await pipe.feed(b"x")
    assert on_overflow.await_count == 1
    assert pipe.decoder.overflowed is False  # 通知后标志复位

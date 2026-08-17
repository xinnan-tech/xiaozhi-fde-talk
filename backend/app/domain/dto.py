"""跨域 DTO（协议无关的数据传输对象）。

AudioFrame / OutboundEvent / TranscriptionResult / LLMRequest/Response。
DTO 数量不多，单文件收拢（不拆 3 个文件）。

这些 DTO 是 transport↔services 之间的契约，使会话层协议无关。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class AudioFrame:
    """协议无关的音频帧。

    session_seq 为 None 时 Runtime 走 fingerprint dedup（兼容无序协议）。
    WS 天然有 seq；MQTT/UDP/QUIC 不保证有序 → None。
    """
    session_seq: Optional[int]
    codec: Literal["webm", "opus", "pcm16k"]
    sample_rate: int
    payload: bytes
    received_at: float


@dataclass
class OutboundEvent:
    """协议无关的出站事件。

    classification 决定 grace 期/断连时的处理：
      - stateless  : 丢弃，bind 后重推
      - stateful   : 丢弃，bind 后推 snapshot
      - critical   : 保留 + 落盘，bind 时 replay
    """
    seq: int                                    # 单调递增
    type: Literal[
        "hello", "asr", "coaching.update",
        "session.ended", "error", "snapshot",
    ]
    payload: dict
    created_at: float
    classification: Literal["stateless", "stateful", "critical"] = "stateless"


@dataclass
class TranscriptionResult:
    """ASR 归一化后的转写结果（adapter → pipeline → runtime）。"""
    text: str
    seg_id: Optional[str] = None
    start_ms: int = 0
    final: bool = True

"""ASR 抽象接口（可插拔端口）。

两类 provider：
  - offline（interface_type="offline"）：整句 PCM → text。实现 transcribe()。
  - stream  （interface_type="stream"）：流式喂 PCM → 收 finalize 的句子。实现 start/feed/stop_stream()。
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

from app.adapters.asr.normalizer import NormalizedText


class ASRProvider:
    """ASR provider 基类。offline 实现 transcribe；stream 实现 start/feed/stop_stream。"""

    interface_type: str = "offline"   # offline / stream

    @property
    def is_alive(self) -> bool:
        """流式连接是否存活（可继续 feed）。offline 无状态，恒 True；stream 子类按 WS 状态覆写。"""
        return True

    # ---- offline ----

    async def transcribe(self, pcm_bytes: bytes) -> Optional[NormalizedText]:
        """整句 PCM（16k 单声道 int16）→ 归一化文本。offline provider 实现。"""
        raise NotImplementedError("offline provider only")

    # ---- stream ----

    async def start_stream(self, on_utterance: Callable[[str, bool], Awaitable[None]]) -> None:
        """开启流式识别。on_utterance(text, is_final) 在每个句子到达时回调。"""
        raise NotImplementedError("streaming provider only")

    async def feed_stream(self, pcm: bytes) -> None:
        """喂一坨 PCM（16k 单声道 int16）。"""
        raise NotImplementedError("streaming provider only")

    async def stop_stream(self) -> None:
        """结束流式（发结束帧 + 关 WS）。"""
        raise NotImplementedError("streaming provider only")

    async def close(self) -> None:
        """释放资源。"""

    async def force_close(self) -> None:
        """强制立即释放（不等 stop_stream 的收尾 drain）。

        重连拆除旧 provider 时调：旧连接的 WS 可能「假活」——仍开但 ASR 会话卡死、
        不再出字——等正常 close() 的收尾（含 recv drain）会拖垮重连。默认退化到 close()，
        流式子类按需覆写为立即关 WS。
        """
        await self.close()

"""断网续传：seq 管理。

seq 是会话级全局帧号，从 0 递增、跨重连不归零。

`consumed_seq` 语义 = **下一个期望的 seq**（= 已喂给 ASR 的帧数；seq 从 0 起）。

放在 services/sessions/ 下：seq 是会话级关注点，由 SessionRuntime 持有；
transport/websocket/resume.py 仅做向后兼容 re-export。
"""
from __future__ import annotations


# 4 字节无符号帧号上限 + 1：超过这个值 consumed_seq 会被推到 2^32，
# 之后所有合法 32-bit seq 都 < consumed_seq 被 should_accept 拒为「old seq」，
# 整段录音期的 audio 帧全被丢弃、ASR 不出字（直到 listen:start 重置 SeqTracker）。
# 边界帧静默 no-op：不推进 consumed_seq，让听音窗重置恢复合法期望。
_SEQ_MAX_EXCLUSIVE = 0x100000000


class SeqTracker:
    def __init__(self, consumed_seq: int = 0) -> None:
        self.consumed_seq = consumed_seq  # 下一个期望 seq

    @property
    def resume_from_seq(self) -> int:
        return self.consumed_seq

    def should_accept(self, seq: int) -> bool:
        """seq >= consumed_seq 才接受；< consumed_seq 是已喂过的重放，跳过防重复。"""
        return seq >= self.consumed_seq

    def mark_consumed(self, seq: int) -> None:
        """收到 seq 后，下一个期望 = seq + 1（取 max 防回退）。

        边界保护：seq 接近 4 字节无符号上限时静默丢弃，避免 consumed_seq 越过
        2^32 后污染整个听音窗。详见 _SEQ_MAX_EXCLUSIVE 注释。
        """
        if seq + 1 >= _SEQ_MAX_EXCLUSIVE:
            return
        if seq + 1 > self.consumed_seq:
            self.consumed_seq = seq + 1

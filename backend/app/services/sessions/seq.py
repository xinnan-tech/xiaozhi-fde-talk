"""断网续传：seq 管理。

seq 是会话级全局帧号，从 0 递增、跨重连不归零。

`consumed_seq` 语义 = **下一个期望的 seq**（= 已喂给 ASR 的帧数；seq 从 0 起）。

放在 services/sessions/ 下：seq 是会话级关注点，由 SessionRuntime 持有；
transport/websocket/resume.py 仅做向后兼容 re-export。
"""
from __future__ import annotations


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
        """收到 seq 后，下一个期望 = seq + 1（取 max 防回退）。"""
        if seq + 1 > self.consumed_seq:
            self.consumed_seq = seq + 1

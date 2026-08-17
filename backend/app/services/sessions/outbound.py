"""出站缓冲：BoundedOutboundBuffer + 三分类。

出站事件按可靠性语义分三类。
  - stateless : coaching.update{recomputing}、hello —— 断连即丢，bind 后重推
  - stateful  : coaching.update{final}、asr{final} —— 断连即丢，bind 后推 snapshot
  - critical  : error、session.ended —— 保留 + 落盘，bind 时 replay

当前实现：critical 事件入有界缓冲，bind 时 replay；
stateless/stateful 不缓冲（由 Runtime 在 bind 时推一次 snapshot 兜底），不做消息级回放。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

# 消息 type → 分类
_CLASSIFICATION: dict[str, str] = {
    "error": "critical",
    "session.ended": "critical",
    "asr": "stateful",
    "coaching.update": "stateful",   # final 走 stateful；recomputing 在下方按 phase 细化
    "hello": "stateless",
    "snapshot": "stateless",
}

_STATELESS_PHASES = {"recomputing"}


def classify(msg: dict) -> str:
    """按消息 type/phase 判定分类。"""
    mtype = msg.get("type", "")
    if mtype == "coaching.update" and msg.get("phase") in _STATELESS_PHASES:
        return "stateless"
    return _CLASSIFICATION.get(mtype, "stateless")


class BoundedOutboundBuffer:
    """有界出站缓冲：只保留 critical 事件，供断连重连后 replay。

    stateless/stateful 不缓冲（用 snapshot 兜底，不做消息级回放）。
    """

    def __init__(self, max_size: int = 100, ttl_s: float = 300.0) -> None:
        self._critical: deque[dict] = deque(maxlen=max_size)
        self._ttl_s = ttl_s
        self._seq = 0

    def next_seq(self) -> int:
        """分配单调递增的出站 seq。"""
        self._seq += 1
        return self._seq

    def retain_critical(self, msg: dict) -> None:
        """把 critical 事件入缓冲（带时间戳，TTL 过期由 purge 清理）。"""
        if classify(msg) != "critical":
            return
        entry = dict(msg)
        entry["_ts"] = time.time()
        self._critical.append(entry)

    def critical_for_replay(self) -> list[dict]:
        """返回未过期的 critical 事件（供 bind 时 replay）。"""
        now = time.time()
        return [ {k: v for k, v in e.items() if k != "_ts"} for e in self._critical if now - e.get("_ts", 0) <= self._ttl_s ]

    def purge(self) -> None:
        """清理过期 critical。"""
        now = time.time()
        while self._critical and now - self._critical[0].get("_ts", 0) > self._ttl_s:
            self._critical.popleft()

    def clear(self) -> None:
        self._critical.clear()
        self._seq = 0

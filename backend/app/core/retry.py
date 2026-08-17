"""退避策略 + 限流工具。

LLM/ASR 调用的退避重试 + 会话创建/LLM 调用限流。
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class BackoffPolicy:
    """指数退避策略。"""
    base_delay: float = 1.0
    max_delay: float = 30.0
    factor: float = 2.0

    def delay_for(self, attempt: int) -> float:
        """第 attempt 次重试的延迟（attempt 从 0 起）。"""
        return min(self.base_delay * (self.factor ** attempt), self.max_delay)


@dataclass
class TokenBucket:
    """令牌桶限流（线程安全需加锁；协程场景用 asyncio.Lock）。

    用法：
        bucket = TokenBucket(capacity=5, refill_per_hour=5)
        if await bucket.try_acquire(user_id):
            ...
    """
    capacity: int
    refill_per_hour: int
    _tokens: float = field(init=False)
    _last_refill: float = field(default_factory=time.monotonic, init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        refill = elapsed * (self.refill_per_hour / 3600.0)
        self._tokens = min(self.capacity, self._tokens + refill)
        self._last_refill = now

    def try_acquire(self) -> bool:
        """非异步版（单线程事件循环下安全）。"""
        self._refill()
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False


@dataclass
class RateLimiter:
    """按 key 限流（如 user_id → 会话创建 5/小时）。

    _buckets 带 FIFO 上限（max_buckets）+ 空闲 TTL（bucket_ttl_s），防止公网分布式
    攻击造无界新 key 导致 OOM。活跃 key 每次 acquire 刷新时间戳，不会被 TTL 清掉。
    """
    capacity: int
    refill_per_hour: int
    max_buckets: int = 10000
    bucket_ttl_s: float = 3600.0
    _buckets: dict[str, tuple[TokenBucket, float]] = field(default_factory=dict, init=False)

    def try_acquire(self, key: str) -> bool:
        now = time.monotonic()
        # TTL 清理空闲 bucket
        self._buckets = {
            k: (b, t) for k, (b, t) in self._buckets.items()
            if now - t < self.bucket_ttl_s
        }
        # FIFO 上限：超量淘汰最旧
        while len(self._buckets) >= self.max_buckets:
            self._buckets.pop(next(iter(self._buckets)))

        entry = self._buckets.get(key)
        if entry is None:
            bucket = TokenBucket(capacity=self.capacity, refill_per_hour=self.refill_per_hour)
            self._buckets[key] = (bucket, now)
            return bucket.try_acquire()
        bucket, _ = entry
        self._buckets[key] = (bucket, now)  # 续期
        return bucket.try_acquire()

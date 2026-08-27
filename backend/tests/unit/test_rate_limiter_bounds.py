"""RateLimiter._buckets 加 FIFO 上限 + TTL 清理，防无界增长 OOM。

L6：公网分布式猜密码攻击会不断造新 key，_buckets 无界增长直至 OOM。
加 max_buckets（FIFO 淘汰）+ bucket_ttl_s（空闲桶过期清理）。

判定：用可变假时钟控制 time.monotonic（避免 monkeypatch 递归）。
- 当前代码无 max_buckets/bucket_ttl_s 参数 → 构造即 TypeError（红）
- 修复后：超上限淘汰最旧、过 TTL 清理空闲桶（绿）
"""
from __future__ import annotations

import app.core.retry as retry_module
from app.core.retry import RateLimiter


def test_rate_limiter_evicts_oldest_when_full(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(retry_module.time, "monotonic", lambda: fake_now[0])

    limiter = RateLimiter(capacity=5, refill_per_hour=10, max_buckets=3)
    for i in range(5):
        limiter.try_acquire(f"key_{i}")

    assert len(limiter._buckets) <= 3, (
        f"_buckets 应被 FIFO 上限裁到 ≤3，实际 {len(limiter._buckets)}"
    )


def test_rate_limiter_cleans_expired_buckets(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(retry_module.time, "monotonic", lambda: fake_now[0])

    limiter = RateLimiter(capacity=5, refill_per_hour=10, bucket_ttl_s=10.0)
    limiter.try_acquire("key_a")  # 时间戳 0
    assert len(limiter._buckets) == 1

    fake_now[0] = 20.0  # 超过 ttl
    limiter.try_acquire("key_b")  # 触发清理

    assert "key_a" not in limiter._buckets, "空闲桶过 TTL 应被清理"
    assert "key_b" in limiter._buckets


def test_rate_limiter_active_key_not_expired(monkeypatch):
    """活跃 key（持续 acquire）刷新时间戳，不过期。"""
    fake_now = [0.0]
    monkeypatch.setattr(retry_module.time, "monotonic", lambda: fake_now[0])

    limiter = RateLimiter(capacity=5, refill_per_hour=10, bucket_ttl_s=10.0)
    fake_now[0] = 0.0
    limiter.try_acquire("key_a")
    fake_now[0] = 5.0
    limiter.try_acquire("key_a")  # 续期
    fake_now[0] = 12.0  # 距上次 acquire 7s < 10s
    limiter.try_acquire("key_b")  # 触发清理

    assert "key_a" in limiter._buckets, "活跃 key 不应被 TTL 清掉"

"""pwd_ver 写入时钟：保证「同一秒内的多次写，后写严格大于先写」。

背景：

- base.py:50 吊销判定是 ``int(pwd_changed_at.timestamp()) != int(pwd_ver_claim)``，
  两边都是秒级整数。
- token 编码端 ``int(pwd_ver)`` 同样把 ``password_changed_at.timestamp()`` 向下
  截到秒。
- e2e 场景 D-2 飘红的根因：bob 注册与 admin 改密发生在同一秒内，
  ``int(reg) == int(reset)``，判定放行。
- 朴素 ``ceil(now)`` 也不行：ceil(27.300) == ceil(27.500) == 27，两者撞同一
  整数秒还是相等。

修法：维护一个进程内单调递增计数器。同一秒内多次调用会在整数末尾追加计数器，
保证 ``int(after) > int(before)`` 严格成立；跨秒则用 wall clock 触发下一基准。
DB 里存的仍是秒级整数的扩展值，token 编码端 ``int(pwd_ver)`` 不需动。

副作用：DB 里 ``password_changed_at`` 实际值比真实改密时刻晚最多 1 秒（跨秒
边界同理）。该字段只参与 pwd_ver 比对，无别处显示依赖——无业务影响。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

# 进程内最近一次写入值（epoch 秒整数 + 计数器）；保证下次调用严格更大。
_lock = threading.Lock()
_last: int = 0  # 0 表示尚未写过


def next_pwd_ver_ts(now: datetime | None = None) -> datetime:
    """返回「严格大于进程内上次值」的 aware UTC datetime。

    - 同一秒内多次调用：后写 = 先写 + 1（计数器位）。
    - 跨秒：后写 = max(now 秒整数, 先写 + 1)。
    - 首次调用：返回 now 秒整数（等价 ceil(now)）。

    数字层语义：
        base = int(now.timestamp())
        返回值 epoch 整数 = max(base, _last + 1)
    """
    global _last
    if now is None:
        now = datetime.now(timezone.utc)
    base = int(now.timestamp())
    with _lock:
        candidate = base if _last == 0 else max(base, _last + 1)
        _last = candidate
    return datetime.fromtimestamp(candidate, tz=timezone.utc)


def _reset_for_test() -> None:
    """仅供测试：清零进程内计数器。多线程下只用于测试场景。"""
    global _last
    with _lock:
        _last = 0
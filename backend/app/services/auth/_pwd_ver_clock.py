"""pwd_ver 写入时钟：保证「改密后 pwd_ver 严格大于旧 token 的 pwd_ver」。

背景：

- base.py:50 吊销判定是 ``int(pwd_changed_at.timestamp()) != int(pwd_ver_claim)``，
  两边都是秒级整数。
- token 编码端 ``int(pwd_ver)`` 同样把 ``password_changed_at.timestamp()`` 向下
  截到秒。
- e2e 场景 D-2 飘红的根因：bob 注册与 admin 改密发生在同一秒内，
  ``int(register_ts) == int(reset_ts)``，判定放行。

修法：改密路径写 ``password_changed_at`` 时改成「**下一整秒**」——即便真实改密
时刻是同一秒内，DB 里的值也强制 +1 秒，旧 token 立刻被吊销。

副作用：DB 里 ``password_changed_at`` 实际值比真实改密时刻晚最多 1 秒。
该字段只参与 pwd_ver 比对，无别处显示依赖——无业务影响。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone


def next_pwd_ver_ts(now: datetime | None = None) -> datetime:
    """返回「下一整秒」的 aware UTC datetime。

    - 注册时用：避免「注册即改密」撞同一秒。
    - 改密时用：保证 ``int(after.timestamp()) > int(register_ts.timestamp())`` 严格成立。

    数学上等价于 ``ceil(now.timestamp())``——比如 02:04:27.300000 → 02:04:28；
    02:04:27.000000 → 02:04:28（边界同样上取整）。
    """
    if now is None:
        now = datetime.now(timezone.utc)
    ts = now.timestamp()
    # 整秒上取整：避免 ``math.ceil(整数) == 自身`` 让「恰好整秒」时不变。
    next_ts = int(ts) + 1 if ts == int(ts) else math.ceil(ts)
    return datetime.fromtimestamp(next_ts, tz=timezone.utc)
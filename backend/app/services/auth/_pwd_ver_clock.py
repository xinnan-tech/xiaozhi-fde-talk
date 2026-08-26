"""pwd_ver 写入时钟：保证「任意两次写，int(after) 严格 > int(before)」。

背景：

- base.py:50 吊销判定 ``int(pwd_changed_at.timestamp()) != int(pwd_ver_claim)``，
  两边都是秒级整数。
- token 编码端 ``int(pwd_ver)`` 同样向下截到秒。
- e2e 场景 D-2 飘红的根因：bob 注册与 admin 改密发生在同一秒内，
  ``int(reg) == int(reset)`` 放行；朴素 ``ceil(now)`` 也救不了——ceil(27.300)
  == ceil(27.500) == 27，两者撞同一整数秒还是相等。

修法：维护一个进程内单调递增的「上次写入值」。同秒内后写 = 先写 +1；
跨秒用 wall clock 推进基准。任意两次调用（含跨进程重启）保证
``int(after) > int(before)``。

**进程重启的种子**：模块加载时 ``_last = 0``，单进程内没问题——前一次写的
更大值已落 DB。但进程重启后新进程的 ``_last`` 必须用「DB 当前最大值」种子，
否则同秒内落库的更大值会被新进程回写覆盖（跌穿 → 旧 token 再次放行）。
启动期调用 ``seed_from_db_max(max_epoch_seconds)`` 灌种子。

**多 worker 部署**：每个 worker 独立 ``_last``。``WEB_CONCURRENCY>=2`` 时
register 落 worker A（基 base），admin reset 落 worker B（B 的 ``_last`` 若
未做 DB 种子 = 0，candidate = base），同值还是会放行。**本模块单进程内有效；
多 worker 下应在 DB 层用 ``UPDATE ... SET password_changed_at = COALESCE(
GREATEST(password_changed_at, ?) + 1, ?)`` 等原子写法兜底**——这块留给
issue 跟进，本 PR 范围仅修「进程内 + 进程重启后」两种场景。

副作用：DB 里 ``password_changed_at`` 实际值可能晚于真实改密时刻（单进程内
累计漂移 + 跨 worker 落点漂移），无业务显示依赖——无影响。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

# 进程内最近一次写入值（epoch 秒整数）；保证下次调用严格更大。
_lock = threading.Lock()
_last: int = 0  # 0 表示尚未写过；启动期应通过 seed_from_db_max 灌入 DB 当前最大值


def next_pwd_ver_ts(now: datetime | None = None) -> datetime:
    """返回「严格大于进程内上次值」的 aware UTC datetime。

    - 同一秒内多次调用：后写 = 先写 + 1（计数器位）。
    - 跨秒：后写 = max(now 秒整数, 先写 + 1)。
    - 未 seed 且首次调用：candidate = int(now) —— **单进程部署足够**；
      进程重启或新 worker 必须先 ``seed_from_db_max``，否则会跌穿已落库值。
    """
    global _last
    if now is None:
        now = datetime.now(timezone.utc)
    base = int(now.timestamp())
    with _lock:
        if _last == 0:
            candidate = base  # 首写兜底；启动期 seed 后此分支实际不会再走
        else:
            candidate = max(base, _last + 1)
        _last = candidate
    return datetime.fromtimestamp(candidate, tz=timezone.utc)


def seed_from_db_max(max_epoch_seconds: int | None) -> None:
    """启动期灌种子：把 ``_last`` 推到 DB 当前最大 ``password_changed_at``。

    调用时机：进程启动 + 在接请求前。``max_epoch_seconds`` 取自 ``SELECT
    MAX(password_changed_at)`` 结果的 ``int(ts.timestamp())``；传 None 视为空表
    跳过。
    """
    global _last
    if max_epoch_seconds is None:
        return
    with _lock:
        if max_epoch_seconds > _last:
            _last = max_epoch_seconds


def _reset_for_test() -> None:
    """仅供测试：清零进程内计数器。多线程下只用于测试场景。"""
    global _last
    with _lock:
        _last = 0
"""会话运行时状态机：4 个子状态。

区别于 domain.session.SessionStatus（持久化层状态：CREATED/IN_PROGRESS/SUSPENDED/...），
RuntimeState 描述的是「会话运行时的聆听子状态」，驱动 force_timer / 管线 的启停：

  LIVE           —— 正在聆听（listen:start）
  LIVE_PAUSED    —— 聆听暂停（listen:stop）；force_timer 暂停、管线保留
  SUSPENDED_LOCAL—— 连接断开、存活窗口内；force_timer 暂停、管线保留
  TERMINATED     —— 结束/窗口过期；Runtime 销毁、管线释放

关键：SUSPENDED_LOCAL 期间暂停 force_timer 和管线，避免 60s × N Runtime 的隐性 OOM
与 LLM 费用浪费。
"""
from __future__ import annotations

from enum import Enum


class RuntimeState(Enum):
    LIVE = "live"
    LIVE_PAUSED = "live_paused"
    SUSPENDED_LOCAL = "suspended_local"
    TERMINATED = "terminated"


# 合法子状态转换
_RUNTIME_TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.LIVE: {RuntimeState.LIVE_PAUSED, RuntimeState.SUSPENDED_LOCAL, RuntimeState.TERMINATED},
    RuntimeState.LIVE_PAUSED: {RuntimeState.LIVE, RuntimeState.SUSPENDED_LOCAL, RuntimeState.TERMINATED},
    RuntimeState.SUSPENDED_LOCAL: {RuntimeState.LIVE, RuntimeState.LIVE_PAUSED, RuntimeState.TERMINATED},
    RuntimeState.TERMINATED: set(),
}


class IllegalRuntimeTransition(Exception):
    pass


class RuntimeStateMachine:
    """Runtime 子状态机。"""

    def __init__(self, initial: RuntimeState = RuntimeState.LIVE_PAUSED) -> None:
        # 初始 LIVE_PAUSED：连接已 bind 但未 listen:start
        self._state = initial

    @property
    def state(self) -> RuntimeState:
        return self._state

    def transition(self, to: RuntimeState) -> None:
        if to not in _RUNTIME_TRANSITIONS.get(self._state, set()):
            raise IllegalRuntimeTransition(
                f"非法运行时状态转换: {self._state.value} → {to.value}"
            )
        self._state = to

    @property
    def is_listening(self) -> bool:
        return self._state == RuntimeState.LIVE

    @property
    def is_suspended(self) -> bool:
        return self._state == RuntimeState.SUSPENDED_LOCAL

    @property
    def is_terminated(self) -> bool:
        return self._state == RuntimeState.TERMINATED

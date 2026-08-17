"""首评生成（无 runtime 的 HTTP 路径）。

有 runtime（在线或寄存）的调用方应直接调 engine.first_generate——同一 state
对象 + 引擎锁，在线时结果顺带经 WS 推送。本模块仅兜「无 runtime」：一次性引擎
在 DB 载入的 state 上生成并落盘。per-session in-flight 锁内重载复查 flag，
防并发请求各持旧快照双算。锁用完回收，不随历史会话数泄漏。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from app.persistence.repositories.interview import interview_repo
from app.services.coaching.engine import CoachingEngine
from app.services.sessions.manager import manager
from app.services.sessions.state import SessionState

_inflight: dict[str, asyncio.Lock] = {}


async def _noop_send(msg: dict) -> None:
    pass


def _release_lock(session_id: str, lock: asyncio.Lock) -> None:
    """用完回收（与 interview_repo._release_save_lock 同一手法）：仅当字典里仍是
    这把锁且无排队等待者。有等待者时删除会让后来者 setdefault 到新锁、与等待者
    并行进临界区，串行化就破了。检查发生在持锁段末尾（finally 到锁实际释放之间
    无 await），无竞态窗口。
    """
    if _inflight.get(session_id) is lock and not lock._waiters:
        del _inflight[session_id]


async def generate_first_batch(session_id: str) -> Optional[SessionState]:
    """无 runtime 时生成首评并落盘（幂等）。返回会话状态；不存在返回 None。"""
    lock = _inflight.setdefault(session_id, asyncio.Lock())
    async with lock:
        try:
            state = await manager.get(session_id)
            if state is None or state.session.first_batch_generated:
                return state
            engine = CoachingEngine(state, _noop_send)
            engine.ainit()

            async def _persist_if_row_exists() -> None:
                # LLM 调用窗口内会话可能被 delete（本路径无 runtime，拦截帮不上），
                # 而 save_state 记录缺失时会重建行——先查行仍在，不在则跳过落盘。
                if await interview_repo.get_session_auto(session_id) is None:
                    return
                await interview_repo.save_state_auto(state)

            engine._persist = _persist_if_row_exists
            await engine.first_generate()
            return state
        finally:
            _release_lock(session_id, lock)

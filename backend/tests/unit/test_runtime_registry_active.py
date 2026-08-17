"""P1-3 · RuntimeRegistry 在线 runtime 注册表不变量测试。

新增 _active 跟踪在线（bound）runtime；park 从 _active 移入 _parked（不删除）；
drop 同时清两者。不变量：

1. _active 与 _parked 互斥（同一 session_id 不同时存在）
2. unregister 仅清 _active，不清 _parked
3. park 后 _active 不留引用
4. all_active 返回所有在线 runtime
5. register/unregister 幂等
"""
from __future__ import annotations

import pytest

from app.domain.session import Session, SessionStatus
from app.services.sessions.runtime import RuntimeRegistry, SessionRuntime
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template


def _make_runtime(sid: str = "s1") -> SessionRuntime:
    tpl = get_template("pm-research")
    session = Session(id=sid, template_id="pm-research", status=SessionStatus.IN_PROGRESS)
    return SessionRuntime(state=SessionState.initial(session, tpl))


@pytest.mark.asyncio
async def test_invariant_1_active_and_parked_mutually_exclusive():
    """_active 与 _parked 不能同时持有同一 session_id。"""
    reg = RuntimeRegistry()
    rt = _make_runtime("s1")
    reg.register("s1", rt)
    assert "s1" in reg._active
    assert "s1" not in reg._parked

    reg.unregister("s1")
    assert "s1" not in reg._active

    reg.park("s1", rt, ttl_s=60.0)
    assert "s1" not in reg._active  # park 不应在 _active 留引用
    assert "s1" in reg._parked
    reg.drop("s1")  # 清理定时器任务


@pytest.mark.asyncio
async def test_invariant_2_unregister_only_clears_active_not_parked():
    """unregister 仅清 _active；drop 同时清两者。"""
    reg = RuntimeRegistry()
    rt = _make_runtime("s1")
    reg.register("s1", rt)
    reg.unregister("s1")
    assert "s1" not in reg._active

    reg.park("s1", rt, ttl_s=60.0)
    reg.unregister("s1")  # park 后再 unregister：_active 已无，不应抛、不清 _parked
    assert "s1" in reg._parked

    reg.drop("s1")
    assert "s1" not in reg._parked


@pytest.mark.asyncio
async def test_invariant_3_park_does_not_leave_active_reference():
    """park 后 _active 必须无该 session_id 引用。"""
    reg = RuntimeRegistry()
    rt = _make_runtime("s1")
    reg.register("s1", rt)
    reg.park("s1", rt, ttl_s=60.0)
    assert "s1" not in reg._active, f"park 后 _active 仍残留: {list(reg._active.keys())}"
    reg.drop("s1")


@pytest.mark.asyncio
async def test_all_active_returns_only_bound_runtimes():
    """all_active 返回 _active 中的 runtime（不含 parked）。"""
    reg = RuntimeRegistry()
    rt1 = _make_runtime("s1")
    rt2 = _make_runtime("s2")
    reg.register("s1", rt1)
    reg.register("s2", rt2)
    reg.park("s1", rt1, ttl_s=60.0)  # park 后 s1 不在 _active

    active = reg.all_active()
    assert len(active) == 1
    assert active[0] is rt2
    reg.drop("s1")


def test_register_unregister_idempotent():
    """重复 register / unregister 不抛（不涉及定时器，无需事件循环）。"""
    reg = RuntimeRegistry()
    rt = _make_runtime("s1")
    reg.register("s1", rt)
    reg.register("s1", rt)  # 二次 register：覆盖（相同实例）
    assert reg._active["s1"] is rt

    reg.unregister("s1")
    reg.unregister("s1")  # 二次 unregister：no-op
    assert "s1" not in reg._active


@pytest.mark.asyncio
async def test_get_finds_runtime_in_active_or_parked():
    """get 统一查找：先 _active 后 _parked（_suspend_idle 需要兼顾两种状态）。"""
    reg = RuntimeRegistry()
    rt = _make_runtime("s1")

    reg.register("s1", rt)  # bound → _active
    assert reg.get("s1") is rt

    reg.park("s1", rt, ttl_s=60.0)  # 断连 → _parked
    assert reg.get("s1") is rt

    reg.drop("s1")  # 清理
    assert reg.get("s1") is None


@pytest.mark.asyncio
async def test_reconnect_within_liveness_reuses_same_runtime():
    """解耦契约：断连 park 后，liveness 窗口内重连必须复用同一 runtime。"""
    reg = RuntimeRegistry()
    sid = "reuse-1"
    rt = _make_runtime(sid)
    reg.register(sid, rt)
    reg.park(sid, rt, ttl_s=60.0)
    assert reg.get_active(sid) is None, "park 后 _active 不应残留"
    assert sid in reg._parked

    retrieved = reg.get_or_create(sid, rt.state)
    assert retrieved is rt, "重连必须复用原 runtime，不得新建（否则 ASR/LLM 重实例化）"
    assert reg.get_active(sid) is rt, "重连后 runtime 应回到 _active"
    assert sid not in reg._parked, "重连后 _parked 应清空该 sid"

    reg.drop(sid)  # 清理定时器


@pytest.mark.asyncio
async def test_parked_reuse_refreshes_session_fields_from_db():
    """寄存期间 PATCH 过 base_info/goal：复用 runtime 时会话级字段必须刷成 DB 现值。

    落盘时会话级字段整段写入——若复用旧快照，重连后第一次落盘就把用户的编辑
    盖回 DB（数据丢失）。consumed_seq 归连接管线管，不得被 DB 值覆盖。
    """
    reg = RuntimeRegistry()
    sid = "patch-1"
    rt = _make_runtime(sid)
    rt.state.session.base_info = {"project": "旧项目"}
    rt.state.session.goal = "旧目标"
    rt.state.session.consumed_seq = 7
    reg.register(sid, rt)
    reg.park(sid, rt, ttl_s=60.0)

    # DB 侧重连前载入的 fresh state：用户 PATCH 后的值 + 老的 consumed_seq
    tpl = get_template("pm-research")
    fresh_session = Session(
        id=sid, template_id="pm-research", status=SessionStatus.IN_PROGRESS,
        base_info={"project": "新项目"}, goal="新目标", consumed_seq=0,
    )
    fresh_state = SessionState.initial(fresh_session, tpl)

    retrieved = reg.get_or_create(sid, fresh_state)
    assert retrieved is rt
    assert retrieved.state.session.base_info == {"project": "新项目"}
    assert retrieved.state.session.goal == "新目标"
    assert retrieved.state.session.consumed_seq == 7, "consumed_seq 归 runtime，不应被 DB 值覆盖"

    reg.drop(sid)

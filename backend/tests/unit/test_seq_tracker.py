"""单元测试：SeqTracker（断网续传帧号去重）。

不依赖外部服务，纯内存验证单调比较与 4 字节无符号边界保护。

关注两条性质：
  1. 单调性：seq >= consumed_seq 接受；< consumed_seq 拒为重放；mark_consumed
     取 max 防回退。
  2. 边界保护：seq 接近 4 字节无符号上限（+1 会越界 2^32）时，mark_consumed
     静默 no-op，避免把 consumed_seq 推到 2^32 后污染整个听音窗——届时所有
     合法 32-bit seq 都会被 should_accept 拒为「old seq」，整段录音期 audio
     全被丢弃、ASR 不出字，直到 listen:start 重置 SeqTracker。
"""
from __future__ import annotations

from app.services.sessions.seq import SeqTracker


# ---- 单调性 ----


def test_should_accept_seq_at_or_above_consumed():
    t = SeqTracker(consumed_seq=5)
    assert t.should_accept(5) is True   # 等于 consumed_seq：下一帧，未喂过
    assert t.should_accept(6) is True
    assert t.should_accept(7) is True


def test_should_reject_seq_below_consumed():
    t = SeqTracker(consumed_seq=5)
    assert t.should_accept(4) is False  # 已喂过
    assert t.should_accept(0) is False
    assert t.should_accept(-1) is False


def test_mark_consumed_advances_monotonically():
    t = SeqTracker(consumed_seq=0)
    t.mark_consumed(0)
    assert t.consumed_seq == 1
    t.mark_consumed(5)
    assert t.consumed_seq == 6
    t.mark_consumed(3)               # 旧 seq：max 防回退
    assert t.consumed_seq == 6       # 不应回退


def test_resume_from_seq_matches_consumed_seq():
    t = SeqTracker(consumed_seq=42)
    assert t.resume_from_seq == 42
    t.mark_consumed(100)
    assert t.resume_from_seq == 101


# ---- 4 字节无符号边界保护 ----


def test_mark_consumed_at_32bit_max_is_silent_noop():
    """seq=0xFFFFFFFF：seq+1=2^32 会污染 consumed_seq。必须静默 no-op。

    期望 consumed_seq 保持原值（不推进、不越过 2^32-1）。
    """
    t = SeqTracker(consumed_seq=0xFFFFFFFE)  # 上一帧 0xFFFFFFFD 推进后的状态
    t.mark_consumed(0xFFFFFFFF)
    # consumed_seq 不应越过 2^32-1；保持原值，未推进
    assert t.consumed_seq == 0xFFFFFFFE
    assert t.consumed_seq < 0x100000000


def test_should_accept_still_accepts_32bit_max_after_attack():
    """攻击后 consumed_seq 不应越过 2^32-1，0xFFFFFFFF 仍应被接受。"""
    t = SeqTracker(consumed_seq=0xFFFFFFFE)
    t.mark_consumed(0xFFFFFFFF)        # 攻击帧：no-op
    assert t.should_accept(0xFFFFFFFF) is True   # 仍接受（>= 当前期望）
    # 关键断言：未出现「任何 32-bit seq 都 < consumed_seq」的死锁
    assert t.consumed_seq <= 0xFFFFFFFF


def test_mark_consumed_repeated_attack_does_not_grow():
    """重复发 0xFFFFFFFF 攻击帧：consumed_seq 不被反复推高。"""
    t = SeqTracker(consumed_seq=0)
    for _ in range(10):
        t.mark_consumed(0xFFFFFFFF)
    assert t.consumed_seq < 0x100000000  # 严格小于 2^32


def test_legitimate_high_seq_still_advances_consumed():
    """紧贴上限的合法帧（0xFFFFFFFE）正常推进；攻击帧（0xFFFFFFFF）no-op。"""
    t = SeqTracker(consumed_seq=0xFFFFFFFD)
    t.mark_consumed(0xFFFFFFFE)        # 合法
    assert t.consumed_seq == 0xFFFFFFFF
    t.mark_consumed(0xFFFFFFFF)        # 边界攻击帧
    assert t.consumed_seq == 0xFFFFFFFF  # 未越过 2^32-1


def test_replay_detection_works_near_boundary():
    """边界附近（consumed_seq=0xFFFFFFFF）的旧帧仍正确拒为重放。"""
    t = SeqTracker(consumed_seq=0xFFFFFFFF)
    assert t.should_accept(0xFFFFFFFE) is False  # 旧帧
    assert t.should_accept(0xFFFFFFFF) is True   # 期望帧
    assert t.should_accept(0) is False           # 回绕后 0 是旧（未 listen_start 重置）


def test_regression_attack_does_not_lock_subsequent_session():
    """场景复现：攻击后 tracker 进入「任何 32-bit seq 都拒收」的死锁状态。

    fix 之前：consumed_seq 跳到 4294967296，所有合法 32-bit seq（≤ 0xFFFFFFFF）
    都 < 4294967296 → should_accept 全 False，mark_consumed 不触发，pipeline.feed
    不跑，ASR 不出字——直到 listen:start 重置 SeqTracker。

    fix 之后：mark_consumed(0xFFFFFFFF) 是 no-op，consumed_seq 保持不变，
    tracker 状态等同于攻击帧没来过，下一帧合法 seq 0 仍可被接受。
    """
    t = SeqTracker(consumed_seq=0)
    # 攻击帧
    t.mark_consumed(0xFFFFFFFF)
    # 关键断言：consumed_seq 没有被攻击推到 2^32——这是修复的本质
    assert t.consumed_seq == 0
    # 攻击被吸收，下一帧合法 seq 0 仍可被接受、推进
    assert t.should_accept(0) is True
    t.mark_consumed(0)
    assert t.consumed_seq == 1
    t.mark_consumed(1)
    assert t.consumed_seq == 2
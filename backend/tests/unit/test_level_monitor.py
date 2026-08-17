"""LevelMonitor 电平监控单元测试。

合成指定 RMS 电平的 PCM（白噪声归一到目标 dBFS）。『语音+停顿』用目标
电平块 + 底噪块交替模拟——真实停顿是房间底噪而非数字静音，数字静音会把
动态差推到 ~185dB，测不到 15dB 动态门的真实工作带（实测语音 ≈34dB）。
覆盖：均匀衰减世界触发、正常/远场压缩/语音埋底噪下不触发、纯噪声与
数字静音不触发、奇数字节不抛异常、reset 重新武装。
"""
from __future__ import annotations

import numpy as np

from app.adapters.asr.level_monitor import LevelMonitor


def _pcm(dbfs: float, seconds: float, seed: int = 42) -> bytes:
    """合成目标 RMS 电平的白噪声 PCM（int16 16k mono）。"""
    n = int(16000 * seconds)
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    x = np.clip(x / np.sqrt(np.mean(x * x)) * (10 ** (dbfs / 20)), -1, 1)
    return (x * 32767).astype(np.int16).tobytes()


def _silence(seconds: float) -> bytes:
    return b"\x00" * (32000 * int(seconds))


def _speech_with_pauses(speech_dbfs: float, floor_dbfs: float, cycles: int = 15) -> bytes:
    """『语音+停顿』：cycles 轮 1s 语音块 + 1s 底噪块（30s @ cycles=15）。

    floor_dbfs 模拟停顿期的房间底噪。系统音量低 = 均匀衰减，语音与底噪
    同比例下降、动态差保持 ~30dB；物理远场 = 语音随距离衰减而底噪不降，
    动态差被压缩。
    """
    return b"".join(
        _pcm(speech_dbfs, 1.0, seed=42 + i) + _pcm(floor_dbfs, 1.0, seed=1000 + i)
        for i in range(cycles)
    )


def _feed_in_chunks(m: LevelMonitor, data: bytes, chunk_s: float = 0.42):
    """按不对齐块的任意大小增量喂入，收集每次返回值。"""
    step = int(32000 * chunk_s)
    return [m.feed(data[i:i + step]) for i in range(0, len(data), step)]


def test_quiet_speech_over_low_floor_fires_once():
    # 均匀衰减世界（系统音量低）：动态差 ≈30dB，落在动态门的真实工作带
    m = LevelMonitor()
    results = _feed_in_chunks(m, _speech_with_pauses(-55, -85))
    fired = [r for r in results if r is not None]
    assert len(fired) == 1
    assert fired[0].p95 < -40
    assert fired[0].delta > 15


def test_normal_speech_never_fires():
    m = LevelMonitor()
    assert all(r is None for r in _feed_in_chunks(m, _speech_with_pauses(-20, -60, cycles=18)))


def test_far_field_compressed_dynamics_not_fired():
    # 物理远场：语音掉得比底噪多，动态差 ≈10dB < 15 → 不触发。刻意的模糊带：
    # 与空房不可区分，选择不打扰；是否放宽门由线上触发日志回路决定。
    m = LevelMonitor()
    assert all(r is None for r in _feed_in_chunks(m, _speech_with_pauses(-45, -55)))


def test_speech_buried_under_floor_not_fired():
    # 语音比底噪还轻（SNR<0）：p95 取更响的底噪块，动态差 ≈5dB → 不触发。
    # 与纯噪声房间在 PCM 上不可区分——拿不准就不打扰，属设计选择。
    m = LevelMonitor()
    assert all(r is None for r in _feed_in_chunks(m, _speech_with_pauses(-55, -50)))


def test_pure_quiet_noise_never_fires():
    # 持续小声环境噪声（无语音动态 = 空房间）：不触发
    m = LevelMonitor()
    assert all(r is None for r in _feed_in_chunks(m, _pcm(-55, 35)))


def test_digital_silence_never_fires():
    # 纯数字静音（死麦）：动态为 0，被动态门排除
    m = LevelMonitor()
    assert all(r is None for r in _feed_in_chunks(m, _silence(35)))


def test_odd_length_feed_does_not_raise():
    m = LevelMonitor()
    m.feed(_pcm(-55, 0.5) + b"\x00")   # 尾带半采样字节：不抛 ValueError、状态不坏
    fired = [r for r in _feed_in_chunks(m, _speech_with_pauses(-55, -85, cycles=25)) if r is not None]
    assert len(fired) == 1


def test_reset_rearms():
    m = LevelMonitor()
    first = [r for r in _feed_in_chunks(m, _speech_with_pauses(-55, -85)) if r is not None]
    assert len(first) == 1          # 周期内恰好一次
    m.reset()
    second = [r for r in _feed_in_chunks(m, _speech_with_pauses(-55, -85)) if r is not None]
    assert len(second) == 1         # reset 重新武装后可再次触发

"""解码后 PCM 的电平监控：检测「持续极低电平」，提醒用户靠近麦克风。

只测量不放大：ASR 特征提取自带归一化，纯电平低不伤害识别；低电平真正的
代价是信噪比低（环境噪声/电噪占比高），事后增益会把噪声一起放大、无法
挽回——现场提示用户才是可行动的修复。

与浏览器 AGC 的分层：AGC 保可识别下限；本监控兜底 AGC 救不回的场景
（系统输入音量近零 / 浏览器无 AGC / 超出最大增益）。AGC 生效时电平被拉回
正常、本监控不触发，属预期分层而非矛盾。
"""
from __future__ import annotations

import math
from collections import deque
from typing import NamedTuple

import numpy as np

SAMPLE_RATE = 16_000
_BLOCK_SAMPLES = 4000            # 统计粒度 250ms（16000 × 0.25）：每块算一个 RMS
_WINDOW_BLOCKS = 120             # 滑窗 120 × 250ms = 30s
_MIN_COVERAGE_BLOCKS = 80        # 窗内攒够 20s 才做判定（避免开麦即判）
_QUIET_DBFS = -40.0              # p95 低于此才提示：正常访谈实测 p95≈-16，触发即
                                 # 比正常低 ≥24dB，且落在实测识别相似度仍 0.988+ 的区间
_SPEECH_RANGE_DB = 15.0          # p95−p10 须高于此（窗内有真实语音动态）：实测语音
                                 # 动态≈34dB、纯环境噪声/停顿 <5dB，判别门两侧各留
                                 # ≥10dB 隔离带；数字静音动态为 0，亦被此门排除


class LevelReading(NamedTuple):
    """一次触发的窗口读数：分位电平与动态差（供日志与帧构造）。"""

    p95: float
    p10: float
    delta: float


def _rms_dbfs(block: np.ndarray) -> float:
    """int16 块 → RMS 电平（dBFS）。全零块返回约 -240。"""
    x = block.astype(np.float64) / 32768.0
    return 20.0 * math.log10(math.sqrt(float(np.mean(x * x))) + 1e-12)


class LevelMonitor:
    """滑动窗口电平监控。

    feed 喂增量 PCM；窗口攒够覆盖率且同时满足「电平低」（p95 < _QUIET_DBFS）
    与「有语音动态」（p95−p10 > _SPEECH_RANGE_DB，排除纯停顿/环境噪声/死麦）
    时返回 LevelReading（p95/p10/delta，供日志与帧构造），每个周期（reset
    之间）至多一次；否则返回 None。
    """

    def __init__(self) -> None:
        self._remainder = np.empty(0, dtype=np.int16)
        self._blocks: deque[float] = deque(maxlen=_WINDOW_BLOCKS)
        self._fired = False

    def reset(self) -> None:
        """新开麦周期：清空窗口与已提示标记。"""
        self._remainder = np.empty(0, dtype=np.int16)
        self._blocks.clear()
        self._fired = False

    def feed(self, pcm: bytes) -> LevelReading | None:
        """喂增量 PCM（int16 16k mono bytes），触发时返回窗口读数。"""
        if len(pcm) % 2:
            pcm = pcm[:-1]        # 丢尾带半采样字节：容忍任意字节边界的调用方
        if pcm:
            self._remainder = np.concatenate(
                [self._remainder, np.frombuffer(pcm, dtype=np.int16)]
            )
        n_blocks = len(self._remainder) // _BLOCK_SAMPLES
        if n_blocks:
            usable = self._remainder[: n_blocks * _BLOCK_SAMPLES].reshape(n_blocks, -1)
            for row in usable:
                self._blocks.append(_rms_dbfs(row))
            self._remainder = self._remainder[n_blocks * _BLOCK_SAMPLES:].copy()
        if self._fired or len(self._blocks) < _MIN_COVERAGE_BLOCKS:
            return None
        p95 = float(np.percentile(self._blocks, 95))
        p10 = float(np.percentile(self._blocks, 10))
        if p95 < _QUIET_DBFS and (p95 - p10) > _SPEECH_RANGE_DB:
            self._fired = True
            return LevelReading(p95, p10, p95 - p10)
        return None

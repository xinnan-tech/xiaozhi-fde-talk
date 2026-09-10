"""e2e audio fixture 完整性 sanity check。

interview.pcm 是 chaos 链路直接灌裸 PCM 的样本，必须保证：
- 字节数严格 = 期望（45s × 16kHz × 1ch × 2B = 1,440,000）
- s16 必须 2 字节对齐（长度偶数）
- 首尾 100 字节非全 0（说明不是空文件 / 静音填充）
- 振幅落在合理区间（不是全 0 也不是全削顶）

任何一项失败都意味着 fixture 在历史抽取时被破坏，后端测试看似跑过实际无声。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

FIXTURE_PATH = (
    Path(__file__).parent.parent / "e2e" / "audio" / "interview.pcm"
)
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2  # s16
DURATION_SECONDS = 45
EXPECTED_BYTES = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH_BYTES * DURATION_SECONDS


def test_pcm_fixture_exists() -> None:
    assert FIXTURE_PATH.is_file(), f"fixture 缺失：{FIXTURE_PATH}"


def test_pcm_fixture_size_matches_45s_16khz_mono_s16() -> None:
    size = FIXTURE_PATH.stat().st_size
    assert size == EXPECTED_BYTES, (
        f"fixture 字节数不符：实际 {size} 期望 {EXPECTED_BYTES}（{DURATION_SECONDS}s × "
        f"{SAMPLE_RATE}Hz × {CHANNELS}ch × {SAMPLE_WIDTH_BYTES}B）"
    )


def test_pcm_fixture_size_is_even_for_s16_alignment() -> None:
    """s16 PCM 要求 2 字节对齐；奇数 = 抽取过程截断了一字节。"""
    size = FIXTURE_PATH.stat().st_size
    assert size % 2 == 0, f"fixture 字节数为奇数（{size}），s16 对齐失败"


def test_pcm_fixture_starts_audio_within_one_second() -> None:
    """首 1 秒内有非零样本——说明不是空文件 / 全程静音。

    实际 fixture 有约 57ms 起始静音（WebM 抽取保留的 Opus 编码器前导），
    但首秒应已有音频；超 1s 仍 0 = 抽取出问题。
    """
    raw = FIXTURE_PATH.read_bytes()
    first_second = np.frombuffer(raw[: 16000 * 2], dtype=np.int16)
    nz = int(np.flatnonzero(first_second).size)
    assert nz > 100, (
        f"fixture 首 1s 内仅 {nz} 个非零样本（疑似抽取失败 / 全程静音）"
    )


def test_pcm_fixture_tail_not_silent() -> None:
    """尾 1 秒内 RMS 显著高于 0——说明不是截断到静音。"""
    raw = FIXTURE_PATH.read_bytes()
    tail = np.frombuffer(raw[-16000 * 2 :], dtype=np.int16).astype(np.float64)
    tail = tail / 32768.0
    rms = float(np.sqrt(np.mean(tail * tail)))
    assert rms > 0.001, f"fixture 尾 1s RMS 过低（{rms:.6f}），疑似静音截断"


def test_pcm_fixture_amplitude_in_reasonable_range() -> None:
    """振幅合理：不全 0、不过削顶。"""
    raw = FIXTURE_PATH.read_bytes()
    samples = np.frombuffer(raw, dtype=np.int16)
    peak = int(np.max(np.abs(samples)))
    assert peak > 100, f"fixture 全程近静音（peak={peak}）"
    # 不要求严格 < 32767（满刻度），但 < 32000 留余量避免量化截断信号。
    assert peak < 32000, f"fixture 严重削顶（peak={peak} ≈ 32767）"


def test_pcm_fixture_rms_above_silence_floor() -> None:
    """整体 RMS > 极低底噪门槛：保证 feed 进 ASR 的不是全静音片段。"""
    raw = FIXTURE_PATH.read_bytes()
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    rms = float(np.sqrt(np.mean(samples * samples)))
    assert rms > 0.001, f"fixture RMS 过低（{rms:.6f}），ASR 不会触发任何识别"
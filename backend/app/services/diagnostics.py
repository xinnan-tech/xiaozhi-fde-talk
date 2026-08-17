"""部署后连通性自检服务。

部署后的 1-click 自检：
- ASR：把内嵌真实样本「龙橙」（tests/fixtures/longcheng.wav，~3.7s）送 FunASR，
  期望返回至少一段中文转写。失败时附带 reason 给前端。
- LLM：发最小提示「你是谁？」，期望收到非空回复。

返回结构统一为：
    {"ok": bool, "code": "ok"|"config_missing"|"unreachable"|"auth"|"quota"|"server",
     "message": "人类可读", "latency_ms": int, "detail": {...可选}}
由 transport 层原样下发，前端渲染。
"""
from __future__ import annotations

import asyncio
import io
import logging
import math
import struct
import time
from pathlib import Path
from typing import Any

import httpx

from app.adapters.asr.funasr_server import FunASRServerProvider
from app.adapters.llm.factory import get_llm
from app.core.config_store import get_config_store
from app.core.exceptions import ASRProviderError, LLMProviderError

logger = logging.getLogger(__name__)

# 内嵌真实样本路径（部署包内）
_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
_REAL_SAMPLE = _FIXTURE_DIR / "longcheng.wav"


# ---------- 错误归因 ----------

def _extract_llm_error(exc: Exception) -> dict[str, Any]:
    """LLM 调用异常 → 结构化结果。

    - 未配置 → config_missing
    - 401/403 → auth
    - 429 / quota / balance / 余额 / 欠费 / 额度 → quota
    - 网络/超时/连接拒绝 → unreachable
    - 其它 → server

    LLMProviderError 在 adapter 层已经聚合并丢了 cause；对它只看字符串信号。
    """
    # LLMProviderError：adapter 已合并重试错误，需用字符串关键字识别
    if isinstance(exc, LLMProviderError):
        msg = str(exc).lower()
        if "未配置" in str(exc) or "api_key" in msg or "base_url" in msg or "model" in msg:
            return {"ok": False, "code": "config_missing",
                    "message": f"LLM 配置缺失：{exc}"}
        if "连接被拒绝" in str(exc) or "connect call failed" in msg or "timeout" in msg \
                or "timed out" in msg or "name or service" in msg \
                or "nodename nor servname" in msg:
            return {"ok": False, "code": "unreachable",
                    "message": f"无法连接 LLM 服务：{exc}"}
        # 原始异常在 str 里（如 "ConnectionError: ...", "HTTPStatusError: ..."）
        return {"ok": False, "code": "server",
                "message": f"LLM 调用异常：{exc}"}
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text or ""
        low = body.lower()
        if status in (401, 403):
            return {"ok": False, "code": "auth",
                    "message": f"鉴权失败（HTTP {status}）：密钥/权限不对，请检查后端配置的 api_key"}
        if status == 429 or "quota" in low or "balance" in low \
                or "余额" in body or "欠费" in body or "额度" in body:
            return {"ok": False, "code": "quota",
                    "message": f"额度/限流（HTTP {status}）：{(body or '')[:200]}"}
        if status in (400, 404):
            return {"ok": False, "code": "config_missing",
                    "message": f"配置错误（HTTP {status}）：{(body or '')[:200]}"}
        return {"ok": False, "code": "server",
                "message": f"LLM 服务异常（HTTP {status}）：{(body or '')[:200]}"}
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError)):
        return {"ok": False, "code": "unreachable",
                "message": f"无法连接 LLM 服务：{type(exc).__name__}: {exc}"}
    return {"ok": False, "code": "server",
            "message": f"LLM 调用异常：{type(exc).__name__}: {exc}"}


def _extract_asr_error(exc: Exception) -> dict[str, Any]:
    """ASR 连接/初始化异常 → 结构化结果。"""
    # ASRProviderError（funasr_server 已包装为带 URL + 中文原因）：直接用其 message
    if isinstance(exc, ASRProviderError):
        code = "unreachable" if "连接被拒绝" in str(exc) or "超时" in str(exc) \
            else "config_missing" if "TLS" in str(exc) or "ws_url" in str(exc) \
            else "server"
        return {"ok": False, "code": code, "message": str(exc)}
    msg = str(exc)
    if isinstance(exc, asyncio.TimeoutError):
        return {"ok": False, "code": "unreachable", "message": "ASR 连接超时"}
    if isinstance(exc, ConnectionError) or "refused" in msg.lower() or "connect call failed" in msg.lower():
        return {"ok": False, "code": "unreachable",
                "message": "ASR 服务连不上（端口未通 / 服务未启动），请确认 FunASR 已启动"}
    if "ssl" in msg.lower() or "certificate" in msg.lower():
        return {"ok": False, "code": "config_missing",
                "message": "ASR TLS 握手失败：检查 ws_url 协议（ws/wss）与证书"}
    if "invaliduri" in msg.lower() or "invaliduri" in type(exc).__name__.lower():
        return {"ok": False, "code": "config_missing",
                "message": "ASR ws_url 格式不正确"}
    return {"ok": False, "code": "server",
            "message": f"ASR 调用异常：{type(exc).__name__}: {(msg or '')[:200]}"}


# ---------- 测试音频 ----------

def _resample_pcm(pcm: bytes, src_rate: int, dst_rate: int, sampwidth: int = 2,
                  channels: int = 1) -> bytes:
    """简单线性重采样（够 ASR 自检用，不是高质量重采样）。"""
    if src_rate == dst_rate:
        return pcm
    n_src = len(pcm) // sampwidth
    n_dst = int(round(n_src * dst_rate / src_rate))
    fmt = "<h" if sampwidth == 2 else "<B"
    samples = list(struct.unpack(f"<{n_src}{'h' if sampwidth == 2 else 'B'}", pcm))
    out = bytearray()
    for i in range(n_dst):
        src_pos = i * src_rate / dst_rate
        i0 = int(src_pos)
        i1 = min(i0 + 1, n_src - 1)
        frac = src_pos - i0
        v = int(samples[i0] * (1 - frac) + samples[i1] * frac)
        if sampwidth == 2:
            v = max(-32768, min(32767, v))
            out += struct.pack("<h", v)
        else:
            out += struct.pack("<B", max(0, min(255, v)))
    return bytes(out)


def _load_real_sample_wav(target_rate: int = 16000) -> bytes | None:
    """读 tests/fixtures/longcheng.wav → 转单声道 + 重采样 → 包成 WAV 字节流。

    立体声（nch>1）按帧平均降混到单声道；任一步异常都返回 None 让调用方
    fallback 到合成 tone（这样诊断不会因样本问题卡死）。
    """
    if not _REAL_SAMPLE.exists():
        return None
    try:
        import wave
        with wave.open(str(_REAL_SAMPLE), "rb") as w:
            src_rate = w.getframerate()
            nch = w.getnchannels()
            sw = w.getsampwidth()
            nframes = w.getnframes()
            raw = w.readframes(nframes)
        if sw != 2:
            return None  # 只支持 16-bit PCM
        if nch > 1:
            # 多通道 → 单声道：按帧平均（简单稳定的下混方式，保留原始音量感）
            samples = struct.unpack(f"<{nframes * nch}h", raw)
            mono = bytearray()
            append = mono.extend
            pack = struct.pack
            for i in range(nframes):
                base = i * nch
                s = sum(samples[base + c] for c in range(nch)) // nch
                append(pack("<h", s))
            raw = bytes(mono)
        if src_rate != target_rate:
            raw = _resample_pcm(raw, src_rate, target_rate, sampwidth=2, channels=1)
        return _pcm_to_wav_bytes(raw, target_rate)
    except Exception as e:  # noqa: BLE001
        logger.warning("加载测试音频失败：%s", e)
        return None


def _synth_test_pcm(sample_rate: int = 16000, duration_s: float = 1.5) -> bytes:
    """合成 1 段带语谱结构特征的 tone（真人样本不可用时的回退）。"""
    n = int(sample_rate * duration_s)
    frames = bytearray()
    for i in range(n):
        seg = i / n
        freq = 220.0 + 220.0 * math.sin(2 * math.pi * 4 * seg)
        env = 0.6 * math.sin(math.pi * seg)
        sample = int(env * 20000 * math.sin(2 * math.pi * freq * i / sample_rate))
        frames += struct.pack("<h", max(-32768, min(32767, sample)))
    return bytes(frames)


def _pcm_to_wav_bytes(pcm: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """裸 PCM(16-bit LE mono) → WAV 字节流。"""
    buf = io.BytesIO()
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    data_size = len(pcm)
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<H", 1))
    buf.write(struct.pack("<H", channels))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", byte_rate))
    buf.write(struct.pack("<H", block_align))
    buf.write(struct.pack("<H", 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm)
    return buf.getvalue()


def _build_test_audio(sample_rate: int) -> bytes | None:
    """优先用真实样本；不可用则回退到合成 tone。

    末尾追加 1000ms 静音 PCM，让 FunASR 2pass 内部 VAD 立刻识别句尾，
    避免等满 30s 句尾超时（短样本 + 末段连续语音 → VAD 不切句）。
    与 funasr_server._TAIL_SILENCE_MS 对齐，确保两条路径行为一致。
    """
    from app.adapters.asr.funasr_server import _TAIL_SILENCE_MS
    raw_pcm: bytes | None = None
    wav = _load_real_sample_wav(sample_rate)
    if wav is not None:
        try:
            import wave
            with wave.open(io.BytesIO(wav), "rb") as w:
                raw_pcm = w.readframes(w.getnframes())
        except Exception:  # noqa: BLE001
            raw_pcm = None
    if raw_pcm is None:
        raw_pcm = _synth_test_pcm(sample_rate)
    # 16k 单声道 int16 = 2 字节/采样
    silence = b"\x00" * (sample_rate * 2 * _TAIL_SILENCE_MS // 1000)
    return _pcm_to_wav_bytes(raw_pcm + silence, sample_rate)


# ---------- ASR 自检 ----------

async def diagnose_asr(timeout_s: float = 10.0) -> dict[str, Any]:
    """连 FunASR → 送测试音频 → 等到 final 或超时 → 返回是否成功 + 转写文本。"""
    cfg = get_config_store()
    ws_url = cfg.get_sync("asr.ws_url") or ""
    sample_rate = int(cfg.get_sync("asr.sample_rate") or "16000")
    if not ws_url:
        return {"ok": False, "code": "config_missing",
                "message": "未配置 asr.ws_url，请到「⚙️ 后端配置」填写"}

    wav_bytes = await asyncio.to_thread(_build_test_audio, sample_rate)
    used_real = wav_bytes is not None and _REAL_SAMPLE.exists()

    provider = FunASRServerProvider()
    provider._ws_url = ws_url
    provider._sample_rate = sample_rate

    utterances: list[str] = []
    final_event = asyncio.Event()

    async def _on_utterance(text: str, is_final: bool) -> None:
        if text:
            utterances.append(text)
        if is_final:
            final_event.set()

    t0 = time.monotonic()
    try:
        await asyncio.wait_for(provider.start_stream(_on_utterance), timeout=min(timeout_s, 5.0))
    except Exception as e:  # noqa: BLE001
        return _extract_asr_error(e) | {"latency_ms": int((time.monotonic() - t0) * 1000)}

    try:
        # wav-mode：把整段 wav 一次性发给 FunASR（与正式访谈客户端用法一致：完整 opus/webm 帧）
        await provider._ws.send(wav_bytes)
        # 触发离线句尾（is_speaking=false 让 FunASR 跑 2pass 离线纠错）
        await provider._ws.send('{"is_speaking": false}'.encode("utf-8"))
        try:
            await asyncio.wait_for(final_event.wait(), timeout=timeout_s - (time.monotonic() - t0))
        except asyncio.TimeoutError:
            return {"ok": False, "code": "server",
                    "message": "ASR 已连接但未返回任何结果（服务僵死？）",
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                    "detail": {"utterances": utterances, "sample": "real" if used_real else "synth"}}
        latency = int((time.monotonic() - t0) * 1000)
        if not utterances:
            # 服务连得上且没崩，但没识别出文字（合成 tone 或静音下的常见情况）
            return {"ok": False, "code": "server",
                    "message": "ASR 连通但未识别出文字（可能 ws_url 指向了空模型 / 测试样本太短）",
                    "latency_ms": latency,
                    "detail": {"utterances": utterances, "sample": "real" if used_real else "synth"}}
        return {"ok": True, "code": "ok",
                "message": "ASR 连通 + 转写成功",
                "latency_ms": latency,
                "detail": {"utterances": utterances, "sample": "real" if used_real else "synth"}}
    except Exception as e:  # noqa: BLE001
        return _extract_asr_error(e) | {"latency_ms": int((time.monotonic() - t0) * 1000),
                                        "detail": {"utterances": utterances,
                                                   "sample": "real" if used_real else "synth"}}
    finally:
        try:
            await provider.close()
        except Exception:
            pass


# ---------- LLM 自检 ----------

async def diagnose_llm(timeout_s: float = 15.0) -> dict[str, Any]:
    """调 LLM 发「你是谁？」，期望非空文本回复。"""
    cfg = get_config_store()
    base_url = cfg.get_sync("llm.base_url") or ""
    api_key = cfg.get_sync("llm.api_key") or ""
    model = cfg.get_sync("llm.model") or ""
    missing = [k for k, v in [("llm.base_url", base_url),
                              ("llm.api_key", api_key),
                              ("llm.model", model)] if not v]
    if missing:
        return {"ok": False, "code": "config_missing",
                "message": f"LLM 未配置（缺失：{', '.join(missing)}），请到「⚙️ 后端配置」补齐"}

    provider = get_llm()
    t0 = time.monotonic()
    try:
        reply = await asyncio.wait_for(
            provider.chat_text("用一句话回答", "你是谁？", retries=0),
            timeout=timeout_s,
        )
        latency = int((time.monotonic() - t0) * 1000)
        text = (reply or "").strip()
        if not text:
            return {"ok": False, "code": "server",
                    "message": "LLM 已连通但返回为空（可能被限流/封禁/请求被拒）",
                    "latency_ms": latency}
        return {"ok": True, "code": "ok",
                "message": "LLM 连通 + 正常返回",
                "latency_ms": latency,
                "detail": {"model": model, "reply": text[:160]}}
    except Exception as e:  # noqa: BLE001
        return _extract_llm_error(e) | {"latency_ms": int((time.monotonic() - t0) * 1000)}


# ---------- 合并 ----------

async def diagnose_all() -> dict[str, Any]:
    """并发跑 ASR + LLM，返回双方结果 + 总评。"""
    asr_res, llm_res = await asyncio.gather(
        diagnose_asr(), diagnose_llm(), return_exceptions=True,
    )

    def _safe(r):
        return r if isinstance(r, dict) else {"ok": False, "error": repr(r)}

    asr_res, llm_res = _safe(asr_res), _safe(llm_res)
    overall = asr_res.get("ok") and llm_res.get("ok")
    return {"ok": overall, "asr": asr_res, "llm": llm_res}
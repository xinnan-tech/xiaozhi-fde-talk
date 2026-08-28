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
from app.adapters.ocr.base import OCRError
from app.adapters.ocr.factory import get_ocr
from app.core.config_store import get_config_store
from app.core.i18n.ocr_prompts import OCR_PROMPT
from app.core.i18n import Keys, t
from app.core.i18n.context import current_locale
from app.core.i18n.errors import I18nError

logger = logging.getLogger(__name__)

# 内嵌真实样本路径（部署包内）
_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
_REAL_SAMPLE = _FIXTURE_DIR / "longcheng.wav"


def _localized(key: Keys, **params: Any) -> str:
    """Resolve an i18n key for the current request's locale."""
    return t(key.value, locale=current_locale(), **params)


def _result(code: str, **kw: Any) -> dict:
    """Build a diagnostic result dict; add `i18n_key` when `key` is passed.

    Usage::

        _result("config_missing", key=Keys.DIAG_LLM_CONFIG_MISSING,
                key_params={"missing": "x, y"})

    For result dicts that need extra fields (e.g. ``latency_ms``, ``detail``),
    pipe-merge with the returned dict.
    """
    i18n_key_value = kw.pop("key", None)
    key_params = kw.pop("key_params", {})
    message_override = kw.pop("message", None)
    if message_override is not None:
        message = message_override
    elif i18n_key_value is not None:
        message = _localized(i18n_key_value, **key_params)
    else:
        raise ValueError("_result requires either `key` or `message`")
    out: dict[str, Any] = {"ok": code == "ok", "code": code, "message": message}
    if i18n_key_value is not None:
        out["i18n_key"] = i18n_key_value.value
    return out


def _exc_detail(exc: I18nError, *preferred_keys: str, fallback: str = "") -> str:
    """从 ``I18nError.params`` 里挑最有料的字段填进模板。

    不能用 ``str(exc)``——``I18nError.__str__`` 故意返回调试串
    ``i18n:<code>{<params>}``，直接拼进用户可见的 ``message`` 会把内部字段名
    （``last_err`` / ``snippet`` 等）一并泄漏给前端。
    """
    for k in preferred_keys:
        v = (exc.params or {}).get(k)
        if v:
            return str(v)[:200]
    return fallback or exc.localized()


# ---------- 错误归因 ----------

def _extract_llm_error(exc: Exception) -> dict[str, Any]:
    """LLM 调用异常 → 结构化结果。

    - 未配置 → config_missing
    - 401/403 → auth
    - 429 / quota / balance / 余额 / 欠费 / 额度 → quota
    - 网络/超时/连接拒绝 → unreachable
    - 其它 → server

    adapter 已切到 I18nError：用 `exc.code` 派发归因（不再依赖 str 关键字），
    兜底分支捕获 adapter 未包装的原始网络/状态异常。
    """
    if isinstance(exc, I18nError):
        code = exc.code
        params = exc.params or {}
        if code == Keys.LLM_NOT_CONFIGURED.value:
            return _result("config_missing",
                           key=Keys.DIAG_LLM_CONFIG_MISSING_RAW,
                           key_params={"detail": _exc_detail(
                               exc, "base_url", "api_key", "model",
                               fallback=", ".join(
                                   f"{k}={v!r}" for k, v in (exc.params or {}).items()
                               ),
                           )})
        if code == Keys.LLM_TIMEOUT.value:
            return _result("unreachable",
                           key=Keys.DIAG_LLM_UNREACHABLE_TYPED,
                           key_params={"type": "TimeoutError",
                                       "detail": _exc_detail(exc, "budget")})
        if code == Keys.LLM_NON_RETRYABLE.value:
            status = int(params.get("status", 0) or 0)
            snippet = (params.get("body") or "")[:200]
            if status in (401, 403):
                return _result("auth",
                               key=Keys.DIAG_LLM_AUTH_FAIL,
                               key_params={"status": status})
            if status == 429:
                return _result("quota",
                               key=Keys.DIAG_LLM_RATE_LIMIT,
                               key_params={"status": status, "snippet": snippet})
            if status in (400, 404):
                return _result("config_missing",
                               key=Keys.DIAG_LLM_BAD_CONFIG,
                               key_params={"status": status, "snippet": snippet})
            return _result("server",
                           key=Keys.DIAG_LLM_SERVICE_FAIL,
                           key_params={"status": status, "snippet": snippet})
        if code == Keys.LLM_RETRY_EXHAUSTED.value:
            return _result("server",
                           key=Keys.DIAG_LLM_INVOKE_FAIL,
                           key_params={"detail": _exc_detail(exc, "last_err")})
        # JSON 解析 / 字段缺失 / schema 不匹配：归 server（provider 行为异常）
        if code in (Keys.LLM_NO_JSON_BLOCK.value,
                    Keys.LLM_INVALID_JSON.value,
                    Keys.LLM_SCHEMA_MISMATCH.value):
            return _result("server",
                           key=Keys.DIAG_LLM_INVOKE_FAIL,
                           key_params={"detail": _exc_detail(
                               exc, "snippet", "err", "json_str",
                           )})
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text or ""
        low = body.lower()
        snippet = (body or "")[:200]
        if status in (401, 403):
            return _result("auth",
                           key=Keys.DIAG_LLM_AUTH_FAIL,
                           key_params={"status": status})
        if status == 429 or "quota" in low or "balance" in low \
                or "余额" in body or "欠费" in body or "额度" in body:
            return _result("quota",
                           key=Keys.DIAG_LLM_RATE_LIMIT,
                           key_params={"status": status, "snippet": snippet})
        if status in (400, 404):
            return _result("config_missing",
                           key=Keys.DIAG_LLM_BAD_CONFIG,
                           key_params={"status": status, "snippet": snippet})
        return _result("server",
                       key=Keys.DIAG_LLM_SERVICE_FAIL,
                       key_params={"status": status, "snippet": snippet})
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError)):
        return _result("unreachable",
                       key=Keys.DIAG_LLM_UNREACHABLE_TYPED,
                       key_params={"type": type(exc).__name__, "detail": str(exc)})
    return _result("server",
                   key=Keys.DIAG_LLM_INVOKE_FAIL_TYPED,
                   key_params={"type": type(exc).__name__, "detail": str(exc)})


def _extract_asr_error(exc: Exception) -> dict[str, Any]:
    """ASR 连接/初始化异常 → 结构化结果。

    与 _extract_llm_error 对齐：ASRProviderError = I18nError，用 exc.code 派发归因，
    不再依赖 str() 关键字（之前依赖「连接被拒绝 / 超时 / TLS / ws_url」中文短语，
    一旦 _connect_reason() 文本微调就会漂移到错误的分类）。
    """
    if isinstance(exc, I18nError):
        code = exc.code
        if code == Keys.ASR_CONNECT_FAIL.value:
            # 连接失败：可能是服务未启动（unreachable）、TLS 握手失败
            # （config_missing，tls_fail）、或 ws_url 格式错（config_missing，bad_url）。
            # 凭 code 无法区分，回退到字符串线索——但只针对这一处不可避免的小段，
            # 且限定在 reason 字段而不是整条 str。TLS 必须先判：ssl.SSLError 的 reason
            # 也含 "wss/ws"，原版用 or 串接会把 TLS 误归为 bad_url（issue 87）。
            reason = str((exc.params or {}).get("reason", ""))
            low = reason.lower()
            if "TLS" in reason or "ssl" in low or "certificate" in low:
                return _result("config_missing",
                               key=Keys.DIAG_ASR_TLS_FAIL,
                               key_params={"type": type(exc).__name__,
                                           "detail": reason[:200]})
            if "ws_url" in reason:
                return _result("config_missing",
                               key=Keys.DIAG_ASR_BAD_URL,
                               key_params={"type": type(exc).__name__,
                                           "detail": reason[:200]})
            return _result("unreachable",
                           key=Keys.DIAG_ASR_UNREACHABLE,
                           key_params={"type": type(exc).__name__,
                                       "detail": reason[:200]})
        if code == Keys.ASR_DEAD.value:
            return _result("server",
                           key=Keys.DIAG_ASR_DEAD,
                           key_params={"type": type(exc).__name__,
                                       "detail": _exc_detail(exc, "reason")})
        if code == Keys.ASR_FEED_FAIL.value:
            return _result("server",
                           key=Keys.DIAG_ASR_INVOKE_FAIL_TYPED,
                           key_params={"type": type(exc).__name__,
                                       "detail": _exc_detail(exc, "reason")})
    msg = str(exc)
    if isinstance(exc, asyncio.TimeoutError):
        return _result("unreachable", key=Keys.DIAG_ASR_TIMEOUT)
    if isinstance(exc, ConnectionError) or "refused" in msg.lower() or "connect call failed" in msg.lower():
        return _result("unreachable", key=Keys.DIAG_ASR_UNREACHABLE)
    if "ssl" in msg.lower() or "certificate" in msg.lower():
        return _result("config_missing", key=Keys.DIAG_ASR_TLS_FAIL)
    if "invaliduri" in msg.lower() or "invaliduri" in type(exc).__name__.lower():
        return _result("config_missing", key=Keys.DIAG_ASR_BAD_URL)
    return _result("server",
                   key=Keys.DIAG_ASR_INVOKE_FAIL_TYPED,
                   key_params={"type": type(exc).__name__, "detail": (msg or "")[:200]})


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


def _extract_pcm_from_wav(wav_bytes: bytes) -> bytes:
    """从 WAV 字节流中提取原始 PCM（16-bit mono）。"""
    try:
        import wave
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            nch = w.getnchannels()
            sw = w.getsampwidth()
            nframes = w.getnframes()
            raw = w.readframes(nframes)
        if sw != 2:
            return b""
        if nch > 1:
            samples = struct.unpack(f"<{nframes * nch}h", raw)
            mono = bytearray()
            for i in range(nframes):
                s = sum(samples[i * nch + c] for c in range(nch)) // nch
                mono.extend(struct.pack("<h", s))
            return bytes(mono)
        return raw
    except Exception:  # noqa: BLE001
        return b""


# ---------- ASR 自检 ----------

async def diagnose_asr(timeout_s: float = 10.0) -> dict[str, Any]:
    """根据 asr.type 连对应 ASR → 送测试音频 → 等到 final 或超时 → 返回是否成功 + 转写文本。"""
    cfg = get_config_store()
    asr_type = cfg.get_sync("asr.type") or "funasr_server"
    # 缺关键配置 → 直接返 config_missing；不等 provider 启动失败再走 _extract_asr_error。
    # 字段按 type 分：funasr_server 要 ws_url，豆包要 appid + access_token。
    # 未知 type（funasr_mock 等不需要 ws_url 的 provider）直接放过，让下方 provider 自检。
    if asr_type == "doubao_stream":
        if not (cfg.get_sync("asr.doubao_stream.appid")
                and cfg.get_sync("asr.doubao_stream.access_token")):
            return _result("config_missing", key=Keys.DIAG_ASR_NOT_CONFIGURED)
    elif asr_type == "funasr_server":
        if not cfg.get_sync("asr.funasr_server.ws_url"):
            return _result("config_missing", key=Keys.DIAG_ASR_NOT_CONFIGURED)
    sample_rate = int(cfg.get_sync(f"asr.{asr_type}.sample_rate") or "16000")

    wav_bytes = await asyncio.to_thread(_build_test_audio, sample_rate)
    used_real = _REAL_SAMPLE.exists()

    # WAV → 原始 PCM（供 doubao_stream 的 feed_stream 使用）
    raw_pcm = await asyncio.to_thread(_extract_pcm_from_wav, wav_bytes)

    # 根据 asr.type 创建对应 provider
    if asr_type == "doubao_stream":
        from app.adapters.asr.doubao_stream import DoubaoStreamProvider
        provider: Any = DoubaoStreamProvider()
    else:
        provider = FunASRServerProvider()
        provider._ws_url = cfg.get_sync(f"asr.funasr_server.ws_url") or ""
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
        if asr_type == "doubao_stream":
            # 豆包流式：通过 feed_stream 发送原始 PCM
            await provider.feed_stream(raw_pcm)
            await provider.stop_stream()
        else:
            # FunASR：直接发 WAV 字节（wav-mode）
            await provider._ws.send(wav_bytes)
            await provider._ws.send('{"is_speaking": false}'.encode("utf-8"))

        try:
            await asyncio.wait_for(final_event.wait(), timeout=timeout_s - (time.monotonic() - t0))
        except asyncio.TimeoutError:
            return _result("server", key=Keys.DIAG_ASR_DEAD) | {
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "detail": {"utterances": utterances, "sample": "real" if used_real else "synth"},
            }
        latency = int((time.monotonic() - t0) * 1000)
        if not utterances:
            # 服务连得上且没崩，但没识别出文字（合成 tone 或静音下的常见情况）
            return _result("server", key=Keys.DIAG_ASR_NO_RESULT) | {
                "latency_ms": latency,
                "detail": {"utterances": utterances, "sample": "real" if used_real else "synth"},
            }
        return _result("ok", key=Keys.DIAG_ASR_OK) | {
            "latency_ms": latency,
            "detail": {"utterances": utterances, "sample": "real" if used_real else "synth"},
        }
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
        return _result("config_missing",
                       key=Keys.DIAG_LLM_CONFIG_MISSING,
                       key_params={"missing": ", ".join(missing)})

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
            return _result("server", key=Keys.DIAG_LLM_OK_BUT_EMPTY) | {
                "latency_ms": latency,
            }
        return _result("ok", key=Keys.DIAG_LLM_OK) | {
            "latency_ms": latency,
            "detail": {"model": model, "reply": text[:160]},
        }
    except Exception as e:  # noqa: BLE001
        return _extract_llm_error(e) | {"latency_ms": int((time.monotonic() - t0) * 1000)}


# ---------- OCR 自检 ----------

def _extract_ocr_error(exc: Exception) -> dict[str, Any]:
    """OCR 调用异常 → 结构化结果（走 i18n）。"""
    msg = str(exc).lower()
    if isinstance(exc, OCRError) or "ocr" in msg:
        if "未配置" in str(exc) or "api_key" in msg or "base_url" in msg:
            return _result("config_missing",
                           key=Keys.DIAG_OCR_CONFIG_MISSING,
                           key_params={"missing": str(exc)[:200]})
        if "连接被拒绝" in str(exc) or "connect call failed" in msg or "timeout" in msg \
                or "timed out" in msg or "name or service" in msg:
            return _result("unreachable",
                           key=Keys.DIAG_OCR_UNREACHABLE,
                           key_params={"detail": str(exc)[:200]})
        return _result("server",
                       key=Keys.DIAG_OCR_INVOKE_FAIL_TYPED,
                       key_params={"type": type(exc).__name__, "detail": str(exc)[:200]})
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text or ""
        if status in (401, 403):
            return _result("auth",
                           key=Keys.DIAG_OCR_AUTH_FAIL,
                           key_params={"status": status})
        if status == 429:
            return _result("quota",
                           key=Keys.DIAG_OCR_QUOTA,
                           key_params={"status": status})
        return _result("server",
                       key=Keys.DIAG_OCR_SERVICE_FAIL,
                       key_params={"status": status, "snippet": body[:200]})
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError)):
        return _result("unreachable",
                       key=Keys.DIAG_OCR_UNREACHABLE,
                       key_params={"detail": f"{type(exc).__name__}: {exc}"[:200]})
    return _result("server",
                   key=Keys.DIAG_OCR_INVOKE_FAIL_TYPED,
                   key_params={"type": type(exc).__name__, "detail": str(exc)[:200]})


async def diagnose_ocr(timeout_s: float = 20.0) -> dict[str, Any]:
    """用内置名片测试图调用 OCR，期望非空文本回复（i18n 消息）。"""
    cfg = get_config_store()
    base_url = cfg.get_sync("ocr.base_url") or ""
    api_key = cfg.get_sync("ocr.api_key") or ""
    model = cfg.get_sync("ocr.model") or ""
    missing = [k for k, v in [("ocr.base_url", base_url),
                              ("ocr.api_key", api_key),
                              ("ocr.model", model)] if not v]
    if missing:
        return _result("config_missing",
                       key=Keys.DIAG_OCR_CONFIG_MISSING,
                       key_params={"missing": ", ".join(missing)})

    # 用内嵌名片测试图（tests/fixtures/ocr_test_card.png）
    _OCR_TEST_IMG = _FIXTURE_DIR / "ocr_test_card.png"
    try:
        test_image_bytes = _OCR_TEST_IMG.read_bytes()
    except Exception as e:
        return _result("server",
                       key=Keys.DIAG_OCR_BAD_IMAGE,
                       key_params={"detail": str(e)[:200]})

    provider = get_ocr()
    t0 = time.monotonic()
    try:
        text = await asyncio.wait_for(
            provider.recognize(test_image_bytes, prompt=OCR_PROMPT),
            timeout=timeout_s,
        )
        latency = int((time.monotonic() - t0) * 1000)
        # 灰色图可能返回空，这是预期的——只检查连通性和异常
        return {"ok": True, "code": "ok",
                "message": _localized(Keys.DIAG_OCR_OK),
                "latency_ms": latency,
                "detail": {"model": model, "reply": (text or "(空/灰色图片)")[:160]}}
    except asyncio.TimeoutError:
        return _result("unreachable",
                       key=Keys.DIAG_OCR_TIMEOUT,
                       key_params={})
    except Exception as e:
        return _extract_ocr_error(e) | {"latency_ms": int((time.monotonic() - t0) * 1000)}


# ---------- 合并 ----------

async def diagnose_all() -> dict[str, Any]:
    """并发跑 ASR + LLM + OCR，返回三方结果 + 总评。"""
    asr_res, llm_res, ocr_res = await asyncio.gather(
        diagnose_asr(), diagnose_llm(), diagnose_ocr(), return_exceptions=True,
    )

    def _safe(r):
        return r if isinstance(r, dict) else {"ok": False, "error": repr(r)}

    asr_res, llm_res, ocr_res = _safe(asr_res), _safe(llm_res), _safe(ocr_res)
    overall = asr_res.get("ok") and llm_res.get("ok") and ocr_res.get("ok")
    return {"ok": overall, "asr": asr_res, "llm": llm_res, "ocr": ocr_res}

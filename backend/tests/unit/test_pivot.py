"""pivot 兜底：LLM 输出脚本不符目标语种 → 切 fallback_lang 重试。

覆盖：
- 主路：output_script 匹配 → 不调 fallback，直接返回 (out, lang)
- pivot 路：output_script 不匹配 → 调 fallback system，effective_lang = fallback_lang
- on_pivot 回调：仅 pivot 时触发
- system_factory 必须以 effective_lang 重建 system
"""
from __future__ import annotations

from typing import Awaitable, Callable

import pytest

from app.core.i18n.pivot import with_lang_fallback
from app.core.i18n.script_detect import detect_script


def _async_identity():
    """Return a call recorder preloaded with single-call success text."""
    pass


# ── 主路：脚本匹配 → 不 pivot ──────────────────────────────


@pytest.mark.asyncio
async def test_no_pivot_when_script_matches():
    calls: list[tuple[str, str]] = []

    async def call(system: str, user: str) -> str:
        calls.append((system, user))
        return "你好世界，本次访谈未提及"  # CJK 匹配 zh_cn

    factory = lambda lang: f"<system lang={lang}>"

    out, eff = await with_lang_fallback(call, "<system lang=zh_cn>", factory, "<user>", "zh_cn")

    assert out == "你好世界，本次访谈未提及"
    assert eff == "zh_cn"
    assert len(calls) == 1
    assert calls[0][0] == "<system lang=zh_cn>"


# ── pivot 路：脚本不匹配 → 切 fallback ───────────────────────


@pytest.mark.asyncio
async def test_pivot_fires_when_script_mismatch():
    calls: list[tuple[str, str]] = []

    async def call(system: str, user: str) -> str:
        calls.append((system, user))
        if "lang=zh_cn" in system:
            return "Hello world, this is English"  # LATIN，不匹配 zh_cn
        return "本中文重試"  # CJK，匹配 en 的 fallback（CJK 不在 en 期望）

    factory = lambda lang: f"<system lang={lang}>"
    out, eff = await with_lang_fallback(call, "<system lang=zh_cn>", factory, "<user>", "zh_cn")

    # 第二次调用一定是 fallback system（en），且 effective_lang = en
    assert len(calls) == 2
    assert calls[1][0] == "<system lang=en>"
    assert eff == "en"
    assert "本中文重試" in out


@pytest.mark.asyncio
async def test_pivot_uses_lang_meta_fallback_lang():
    """fallback_lang 从 _LANG_META 读（默认 en），不写死。"""
    calls: list[tuple[str, str]] = []

    async def call(system: str, user: str) -> str:
        calls.append((system, user))
        # 中文 → 不匹配 ru（期望 CYRILLIC/LATIN），触发 pivot
        return "你好中文测试"

    factory = lambda lang: f"<system lang={lang}>"
    out, eff = await with_lang_fallback(call, "<system lang=ru>", factory, "<user>", "ru")
    assert eff == "en"
    assert len(calls) == 2
    assert "lang=en" in calls[1][0]


# ── on_pivot 回调 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_pivot_called_only_when_pivot_fires():
    seen: list[tuple[str, str, str]] = []

    def cb(req: str, obs: str, fb: str) -> None:
        seen.append((req, obs, fb))

    async def call(system: str, user: str) -> str:
        if "lang=zh_cn" in system:
            return "Hello English"
        return "中文兜底"

    factory = lambda lang: f"<system lang={lang}>"

    # 主路：on_pivot 不应被调用
    async def call_match(system: str, user: str) -> str:
        return "你好世界"
    out, eff = await with_lang_fallback(call_match, "<system lang=zh_cn>", factory, "<user>", "zh_cn", on_pivot=cb)
    assert seen == []
    assert eff == "zh_cn"

    # pivot 路：on_pivot 调用一次
    await with_lang_fallback(call, "<system lang=zh_cn>", factory, "<user>", "zh_cn", on_pivot=cb)
    assert len(seen) == 1
    req, obs, fb = seen[0]
    assert req == "zh_cn"
    assert obs == "LATIN"
    assert fb == "en"


@pytest.mark.asyncio
async def test_on_pivot_callback_exception_swallowed():
    """on_pivot 抛错不应影响主流程——埋点失败容错。"""

    def bad_cb(*args, **kwargs):
        raise RuntimeError("telemetry exploded")

    async def call(system: str, user: str) -> str:
        if "lang=vi" in system:
            return "中文错误"  # 不匹配 vi
        return "中文兜底"

    factory = lambda lang: f"<system lang={lang}>"
    out, eff = await with_lang_fallback(call, "<system lang=vi>", factory, "<user>", "vi", on_pivot=bad_cb)
    assert eff == "en"
    assert out == "中文兜底"


# ── LLMError 不被 pivot 接（保留调用方 except 语义）─────────


@pytest.mark.asyncio
async def test_llm_error_propagates_not_caught_by_pivot():
    from app.adapters.llm.base import LLMError

    async def call(system: str, user: str) -> str:
        raise LLMError("test llm boom", http_status=502)

    factory = lambda lang: "<sys>"
    with pytest.raises(LLMError, match="test llm boom"):
        await with_lang_fallback(call, "<sys>", factory, "<user>", "zh_cn")


# ── 边界：lang 大小写 / 空 ──────────────────────────────────


@pytest.mark.asyncio
async def test_uppercase_lang_normalized():
    calls: list[tuple[str, str]] = []

    async def call(system: str, user: str) -> str:
        calls.append((system, user))
        return "你好世界"

    factory = lambda lang: f"<system lang={lang}>"
    # 主路 system 由调用方按归一后 lang 构建；pivot 归一 lang 用于查 _LANG_META 与
    # fallback_lang 选择，system 字面值不变（factory 用归一后 lang 时才会 lowercase）。
    out, eff = await with_lang_fallback(call, "<system lang=zh_cn>", factory, "<user>", "ZH_CN")
    assert eff == "zh_cn"  # lowercase normalized
    assert calls[0][0] == "<system lang=zh_cn>"


# ── fallback 后复检：兜底真实有效率观测（同事 4）─────────────


@pytest.mark.asyncio
async def test_fallback_also_mismatched_logs_error(caplog):
    """fallback 输出仍不匹配 → logger.error，不打 warning 避免埋点过载。

    场景：vi 请求 LLM 输出中文（不匹配 vi）→ pivot 切 en → LLM 仍写中文
    （en 系统 + LLM 没认真按 en 写）→ 检测 mismatch → logger.error。
    """
    import logging

    async def call(system: str, user: str) -> str:
        if "lang=vi" in system:
            return "中文错误内容"  # vi 期望 LATIN
        return "中文错误内容"  # en fallback 也写中文 → 不匹配 en

    factory = lambda lang: f"<system lang={lang}>"

    with caplog.at_level(logging.ERROR, logger="app.core.i18n.pivot"):
        out, eff = await with_lang_fallback(call, "<system lang=vi>", factory, "<user>", "vi")
    assert eff == "en"
    # logger.error 应包含「pivot fallback also mismatched」
    assert any(
        "pivot fallback also mismatched" in rec.message
        for rec in caplog.records
    ), "fallback 复检 mismatch 必须打 logger.error"


@pytest.mark.asyncio
async def test_fallback_matches_no_error_log(caplog):
    """fallback 输出匹配 → 不打 logger.error。"""
    import logging

    async def call(system: str, user: str) -> str:
        if "lang=vi" in system:
            return "中文错误内容"
        return "Hello English world"  # en fallback 写英文 → 匹配 en

    factory = lambda lang: f"<system lang={lang}>"

    with caplog.at_level(logging.ERROR, logger="app.core.i18n.pivot"):
        await with_lang_fallback(call, "<system lang=vi>", factory, "<user>", "vi")
    assert not any(
        "pivot fallback also mismatched" in rec.message
        for rec in caplog.records
    )


# ── observed_script 用 values 不被 raw JSON 稀释（同事 6.2）───


@pytest.mark.asyncio
async def test_observed_script_uses_values_not_raw_json(caplog):
    """pivot.py:63 的 observed 对剥结构字符的 values 跑——raw JSON 键名稀释
    会恒判 LATIN，应复用 values 版。

    场景：LLM 写中文 reason + Latin 缩写 → JSON 结构字符多 → 主脚本如果
    按 raw text 跑会判 LATIN → 误导日志。values 版跑出 CJK。
    """
    import logging

    raw_json = (
        '{"items":[{"id":"q1","text":"能不能描述下AI项目",'
        '"reason":"用户背景 CTO 10K","status":"todo",'
        '"covered_segments":[],"corrected_segments":{}}]}'
    )

    async def call(system: str, user: str) -> str:
        if "lang=zh_cn" in system:
            return raw_json  # zh_cn 期望 CJK，但 JSON 结构 + values 含 Latin 缩写
        return "Hello English"

    factory = lambda lang: f"<system lang={lang}>"

    with caplog.at_level(logging.WARNING, logger="app.core.i18n.pivot"):
        await with_lang_fallback(call, "<system lang=zh_cn>", factory, "<user>", "zh_cn")
    # 因为 zh_cn 主脚本仍是 CJK（values 主体），匹配 → 不触发 pivot，无 warning。
    assert not any(
        "pivot fired" in rec.message
        for rec in caplog.records
    )
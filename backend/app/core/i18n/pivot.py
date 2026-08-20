"""pivot 兜底：LLM 输出脚本与目标语种不符时切 fallback_lang 重试一次。

调用方传 (call, system_factory, user, lang)：
- call: 异步 (system, user) -> str（chat_text 风格）
- system_factory: 同步 lang -> system_prompt（_report_system / build_system 等）
- user: 不变
- lang: 用户期望语种

pivot 先用目标语种 system 调一次，detect_language_match 通过 → 直接返回；
不符则切到 fallback_lang（_LANG_META 默认 en）system 重试一次。

返回 (output, effective_lang)——调用方需把 effective_lang 传给：
- _fill_dangling_labels（决定兜底短语）
- 缓存标签 / 日志（pivot 后用 fallback_lang）

不接 LLMError：调用方的现有 except 已处理「LLM 完全失败」语义；pivot 只关心
「LLM 通了但输出语言错」的窄场景，避免吞错。
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from app.core.i18n.lang_meta import get_lang_meta
from app.core.i18n.script_detect import detect_language_match_json, detect_script

logger = logging.getLogger(__name__)

# type aliases —— 单纯为了 _with_lang_fallback 签名可读
CallFn = Callable[[str, str], Awaitable[str]]
SystemFactory = Callable[[str], str]


async def _with_lang_fallback(
    call: CallFn,
    system: str,
    system_factory: SystemFactory,
    user: str,
    lang: str,
    *,
    on_pivot: Callable[[str, str, str], None] | None = None,
) -> tuple[str, str]:
    """调 call；若输出脚本与 lang 不符 → fallback_lang system 重试一次。

    system 是主路 system（调用方已构建好——保证 spy 能看到首次构建）。
    system_factory 仅在 mismatch 时调用，按 fallback_lang 重建 system。

    on_pivot 回调签名：(requested_lang, observed_script, fallback_lang) -> None
    用于打点 / 埋指标，不传播异常。

    Returns: (output_text, effective_lang)
    """
    requested = (lang or "zh_cn").lower()
    out = await call(system, user)
    if detect_language_match_json(out, requested):
        return (out, requested)

    fallback_lang = get_lang_meta(requested).fallback_lang
    observed = detect_script(out)
    if on_pivot:
        try:
            on_pivot(requested, observed, fallback_lang)
        except Exception:  # noqa: BLE001 — 埋点失败不影响主流程
            logger.exception("pivot on_pivot callback raised")
    logger.warning(
        "pivot fired: requested=%s observed_script=%s retry=%s",
        requested, observed, fallback_lang,
    )
    out = await call(system_factory(fallback_lang), user)
    return (out, fallback_lang)
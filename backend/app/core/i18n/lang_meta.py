"""LLM 输出语种元数据：单一真源。

所有 LLM 输出语种相关 dict（_FALLBACK_BY_LANG、ENUM_KEYS["llm.output_language"]、未来
阶段的 _LANG_META 派生 directive）都从此处派生——任一语种增删只需改这一处。

设计要点：
- LangMeta 用 frozen dataclass，键名稳定可读。
- 头部 10 语种手写；长尾（ar/pt 等）暂不在表，靠 fallback_lang="en" 兜底。
- _derived_fallback_phrases() 返回 dict[str, str]，保持 _FALLBACK_BY_LANG 接口不变——
  _fill_dangling_labels(md, language=...) 等现有调用方零修改。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LangMeta:
    """LLM 输出语种元数据。

    Attributes:
        native_name: 语种母语写法，用于 prompt 指令（"Tiếng Việt" / "繁體中文"）。
        english_name: 英文写法，用于 LLM 跨语种理解（"Vietnamese" / "Traditional Chinese"）。
        bcp47: BCP-47 标签，用于跨系统 locale 协商（"vi-VN" / "zh-TW"）。
        fallback_lang: LLM 输出语种错或 LLM 调用失败时，pivot 切到这个语种重试。
    """

    native_name: str
    english_name: str
    bcp47: str
    fallback_lang: str


# 头部 10 语种：zh_cn/zh_tw/en 内部核心 + vi/ru/ko/ja/fr/de/es 常见扩展。
# 长尾语种暂不写——pivot fallback_lang="en" 兜底，长尾出现时再加 dict 一行。
_LANG_META: dict[str, LangMeta] = {
    "zh_cn": LangMeta("简体中文", "Simplified Chinese", "zh-CN", "en"),
    "zh_tw": LangMeta("繁體中文", "Traditional Chinese", "zh-TW", "en"),
    "en":    LangMeta("English",  "English",             "en-US", "en"),
    "vi":    LangMeta("Tiếng Việt", "Vietnamese",        "vi-VN", "en"),
    "ru":    LangMeta("Русский",   "Russian",            "ru-RU", "en"),
    "ko":    LangMeta("한국어",     "Korean",             "ko-KR", "en"),
    "ja":    LangMeta("日本語",     "Japanese",           "ja-JP", "en"),
    "fr":    LangMeta("Français",  "French",             "fr-FR", "en"),
    "de":    LangMeta("Deutsch",   "German",             "de-DE", "en"),
    "es":    LangMeta("Español",   "Spanish",            "es-ES", "en"),
}


def get_lang_meta(lang: str) -> LangMeta:
    """查 _LANG_META 表。

    三段 fallback 语义：
    - None / 空串 → zh_cn（与生产 `(lang or "zh_cn").lower() or "zh_cn"` 模式一致，
      保持向后兼容，避免 LLM 默认走英文 base 把现有中文用户惊到）。
    - 已知 lang → 直接查表。
    - 未知 lang（如 ar / pt / sw 等长尾）→ en（pivot fallback_lang 兜底，
      长尾不在表里时不会因 KeyError 阻塞）。
    """
    if not lang:
        return _LANG_META["zh_cn"]
    return _LANG_META.get(lang.lower(), _LANG_META["en"])


# 兜底短语按语种切——与各 prompt base 末尾 directive 内嵌短语严丝合缝。
# 避免 LLM 输出正确英文报告后被后处理注入中文（之前硬编码「本次访谈未提及」时的隐性 bug）。
# 派生自 _LANG_META：未来加语种只需改 _LANG_META + 在此加一行短语。
_FALLBACK_PHRASES: dict[str, str] = {
    "zh_cn": "本次访谈未提及",
    "zh_tw": "本次訪談未提及",
    "en":    "Not mentioned in this interview.",
    "vi":    "Không được đề cập trong cuộc phỏng vấn này.",
    "ru":    "Не упомянуто в этом интервью.",
    "ko":    "이번 인터뷰에서 언급되지 않음.",
    "ja":    "このインタビューでは言及されていません。",
    "fr":    "Non mentionné lors de cet entretien.",
    "de":    "In diesem Interview nicht erwähnt.",
    "es":    "No mencionado en esta entrevista.",
}


def derived_fallback_phrases() -> dict[str, str]:
    """对外暴露兜底短语 dict——现有 _FALLBACK_BY_LANG 改用此派生。

    返回 dict 副本：调用方修改不会污染模块级常量。
    """
    return dict(_FALLBACK_PHRASES)


def derived_output_language_enum() -> set[str]:
    """对外暴露 llm.output_language 合法枚举——config_store.ENUM_KEYS 改用此派生。"""
    return set(_LANG_META.keys())
"""访谈信息提取 prompt：单一英文 base + 程序内语种 directive 字典。

`/extract` 端点是 OCR / 粘贴 / 语音转写三条路径的汇聚点——统一在此按
`llm.output_language` 把任意原文整理成用户偏好语言的字段值。

base 全英文 + directive 用模块级 Python dict（不再是 i18n 文件 key）——这些
指令文案是 LLM 提示模板的一部分，必须保持全英文且不被 i18n 翻译污染，
与 _LANG_META 键集合同步。未知 lang 在此显式回退到 en。
"""
from __future__ import annotations

from app.core.i18n.lang_meta import _LANG_META


_EXTRACT_BASE = """You are an interview information extraction assistant. You specialize in extracting structured information from business cards (OCR scans), pasted text, and voice transcripts.

## Source Text (possibly from OCR / paste / ASR)
{transcript}

## Current Values (already filled by user, used as baseline)
{current_values}

## Today's Date
**Today = {today}**
For relative time expressions ("tomorrow 3pm", "next week"), you MUST resolve based on this date.

## Field Types
- datetime: format YYYY-MM-DDTHH:MM, **year is {today_year}** (not other years)
- duration: return number only (minutes)
- text: return original text or semantic summary

## Extraction Principles
1. Output MUST only contain these keys: {fields}. Do NOT create new keys.
2. **Append-merge**: append new names to `interviewee` (joined with ","); append new companies/services to `project` (joined with ","). Do NOT overwrite.
3. Existing field values MUST NOT be deleted; only appended.
4. If source text lacks info for a field, keep the original value.
5. Return ONLY the JSON object. No explanation, no code blocks.

## Language Directive
{extract_directive}
"""


# 与 _LANG_META 同步：每个 lang 一句「写全 XX 语」指令，统一英文模板语料，
# native_name 用 LangMeta 自带的写法（"Tiếng Việt" / "繁體中文"）。
_EXTRACT_DIRECTIVES: dict[str, str] = {
    "zh_cn": "Write all field values in 简体中文 (Simplified Chinese). Translate the source text to 简体中文 as needed.",
    "zh_tw": "Write all field values in 繁體中文 (Traditional Chinese). Translate the source text to 繁體中文 as needed.",
    "en":    "Write all field values in English (English). Translate the source text to English as needed.",
    "vi":    "Write all field values in Tiếng Việt (Vietnamese). Translate the source text to Tiếng Việt as needed.",
    "ru":    "Write all field values in Русский (Russian). Translate the source text to Русский as needed.",
    "ko":    "Write all field values in 한국어 (Korean). Translate the source text to 한국어 as needed.",
    "ja":    "Write all field values in 日本語 (Japanese). Translate the source text to 日本語 as needed.",
    "fr":    "Write all field values in Français (French). Translate the source text to Français as needed.",
    "de":    "Write all field values in Deutsch (German). Translate the source text to Deutsch as needed.",
    "es":    "Write all field values in Español (Spanish). Translate the source text to Español as needed.",
}


def _extract_directive(lang: str) -> str:
    """从模块级 dict 读 directive 文案。

    lang 后缀用 _LANG_META 短码（zh_cn/zh_tw/en/vi/...），不用 bcp47（zh-CN）——
    跟 _LANG_META 键一致避免歧义。未知 lang 回退到 en。
    """
    lang_key = (lang or "zh_cn").lower()
    canonical_key = lang_key if lang_key in _LANG_META else "en"
    return _EXTRACT_DIRECTIVES[canonical_key]


def build_extract_system(
    lang: str = "zh_cn",
    *,
    today: str,
    current_values: str,
    transcript: str,
    fields: list[str],
) -> str:
    today_year = today.split("-")[0] if today else ""
    return _EXTRACT_BASE.format(
        today=today,
        today_year=today_year,
        current_values=current_values,
        transcript=transcript,
        fields=", ".join(fields),
        extract_directive=_extract_directive(lang),
    )
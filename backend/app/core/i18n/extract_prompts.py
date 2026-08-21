"""访谈信息提取 prompt：单一英文 base + i18n 参数化指令。

`/extract` 端点是 OCR / 粘贴 / 语音转写三条路径的汇聚点——统一在此按
`llm.output_language` 把任意原文整理成用户偏好语言的字段值。

base 全英文 + directive 走 i18n.translator.t() 读取，遵循「单一英文 base +
文案归 i18n 文件」原则。`i18n.extract.directive.{lang}` 跟 `_LANG_META` 键集合同步——
未知 lang 在此显式回退到 en（写死 locale="en-US" 读 en_US.json 单源）。
"""
from __future__ import annotations

from app.core.i18n.lang_meta import _LANG_META
from app.core.i18n.translator import t


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


def _extract_directive(lang: str) -> str:
    """从 i18n.translator.t() 读 directive 文案（不在 Python 硬编码）。

    lang 后缀用 _LANG_META 短码（zh_cn/zh_tw/en/vi/...），不用 bcp47（zh-CN）——
    跟 _LANG_META 键一致避免歧义。directive 文案统一英文，写死 locale="en-US"。
    """
    lang_key = (lang or "zh_cn").lower()
    canonical_key = lang_key if lang_key in _LANG_META else "en"
    return t(f"i18n.extract.directive.{canonical_key}", locale="en-US")


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

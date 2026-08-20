"""OCR 提示词：单一英文 base（不需要 directive 注入——OCR 输出语种 = 图片语种）。"""
from __future__ import annotations

import re

from app.core.i18n.ocr_prompts import OCR_PROMPT


def test_ocr_prompt_is_non_empty_string():
    assert isinstance(OCR_PROMPT, str)
    assert len(OCR_PROMPT.strip()) > 0


def test_ocr_prompt_is_english_no_cjk():
    """OCR prompt 应为纯英文（CJK 字符会污染 LLM 在非中文图片上的 OCR 表现）。"""
    cjk = re.findall(r"[一-鿿]", OCR_PROMPT)
    assert not cjk, f"OCR_PROMPT 含 CJK: {cjk}"


def test_ocr_prompt_mentions_extract_or_text():
    """prompt 应明确指示「提取文字」的语义。"""
    lower = OCR_PROMPT.lower()
    assert any(kw in lower for kw in ("extract", "transcribe", "recognize", "read")), (
        f"OCR_PROMPT 缺提取意图关键词: {OCR_PROMPT}"
    )
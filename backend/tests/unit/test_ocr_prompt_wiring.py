"""OCR 路由 + adapter 的 prompt 真源 = OCR_PROMPT。

路由与 adapter 默认 prompt 统一引用 OCR_PROMPT，不再硬编码中文。
"""
from __future__ import annotations

import inspect

from app.core.i18n.ocr_prompts import OCR_PROMPT


def test_ocr_route_uses_ocr_prompt_constant():
    """路由 /ocr 调用 ocr.recognize 时应传 OCR_PROMPT，不再传中文字符串字面量。"""
    from app.transport.http.routes.interviews import recognize_image

    src = inspect.getsource(recognize_image)
    assert "这是一张名片" not in src, f"路由还有中文 OCR prompt 字面量: {src[:500]}"
    assert "OCR_PROMPT" in src, "路由未引用 OCR_PROMPT 常量"


def test_openai_compatible_adapter_default_is_ocr_prompt():
    """openai_compatible.OCRProvider 子类的 recognize 默认 prompt 来自 OCR_PROMPT。"""
    from app.adapters.ocr.openai_compatible import OpenAICompatibleOCRProvider

    sig = inspect.signature(OpenAICompatibleOCRProvider.recognize)
    default = sig.parameters["prompt"].default
    assert default == OCR_PROMPT, f"default = {default!r}, expected OCR_PROMPT"


def test_base_class_default_is_ocr_prompt():
    """OCRProvider 基类 ABC 的 recognize 默认 prompt 来自 OCR_PROMPT。"""
    from app.adapters.ocr.base import OCRProvider

    sig = inspect.signature(OCRProvider.recognize)
    default = sig.parameters["prompt"].default
    assert default == OCR_PROMPT, f"default = {default!r}, expected OCR_PROMPT"


def test_init_module_default_is_ocr_prompt():
    """app.adapters.ocr.__init__ 暴露的 OCRProvider 默认 prompt 来自 OCR_PROMPT。"""
    from app.adapters.ocr import OCRProvider as InitOCRProvider

    sig = inspect.signature(InitOCRProvider.recognize)
    default = sig.parameters["prompt"].default
    assert default == OCR_PROMPT, f"default = {default!r}, expected OCR_PROMPT"

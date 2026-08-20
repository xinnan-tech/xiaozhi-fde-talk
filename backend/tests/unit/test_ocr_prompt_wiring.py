"""OCR 路由的 prompt 真源 = OCR_PROMPT。

路由层调 ocr.recognize 时必须传 OCR_PROMPT，不再传中文字符串字面量。
adapter / 基类默认值的「prompt = OCR_PROMPT」是源码字面量，断言它等于
OCR_PROMPT 等于读源码再读源码，恒真。运行期回归靠 e2e 链路测断言。
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
"""OCR 提示词：单一英文 base。

OCR 输出语种由图片本身决定（不是用户偏好），所以不需要 directive 注入——
单一英文 prompt 在中文/英文/混合名片图片上行为一致。

调用方（adapter 默认 + 路由层）统一引用 `OCR_PROMPT`，避免硬编码漂移。
"""
from __future__ import annotations

OCR_PROMPT = (
    "Extract all text from this image EXACTLY as it appears. "
    "Do NOT translate. Do NOT convert between Simplified and Traditional Chinese. "
    "Preserve the original layout and formatting. "
    "Return only the extracted text."
)

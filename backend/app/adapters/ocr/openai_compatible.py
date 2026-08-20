"""OpenAI 兼容视觉模型 OCR（qwen-vl-plus / gpt-4o / gemini 等）。

支持 base64 编码的图片输入，通过 /chat/completions 接口调用视觉模型提取文字。
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Optional

import httpx

from app.adapters.ocr.base import OCRError, OCRProvider
from app.core.i18n.ocr_prompts import OCR_PROMPT
from app.core.retry import BackoffPolicy

logger = logging.getLogger(__name__)

# OCR 调用超时（比普通 LLM 略长，因为图片编码/传输更耗时）
_OCR_TIMEOUT_S = 30.0


def _image_to_data_url(image_bytes: bytes) -> str:
    """根据图片魔数（magic bytes）返回合适的 mime-type 和 base64 data-url。"""
    if image_bytes.startswith(b"\xff\xd8"):
        mime = "image/jpeg"
    elif image_bytes.startswith(b"\x89PNG"):
        mime = "image/png"
    elif image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/jpeg"  # 默认 JPEG
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


class OpenAICompatibleOCRProvider(OCRProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = _OCR_TIMEOUT_S,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = httpx.Timeout(
            pool=5.0, connect=10.0, write=10.0, read=timeout_s
        )
        self._client = httpx.AsyncClient(timeout=self._timeout)

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._api_key and self._model)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, body: dict, retries: int) -> str:
        """POST chat/completions（视觉模式），返回 content 文本。"""
        if not self.configured:
            raise OCRError("OCR 未配置（ocr.base_url / ocr.api_key / ocr.model）")
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        backoff = BackoffPolicy(base_delay=1.0, max_delay=10.0, factor=2.0)
        last_err: Optional[str] = None
        for attempt in range(retries + 1):
            try:
                t0 = time.monotonic()
                resp = await self._client.post(url, headers=headers, json=body)
                status = resp.status_code
                if status < 400:
                    try:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"] or ""
                    except (ValueError, KeyError, IndexError, TypeError) as e:
                        last_err = f"响应非标准格式: {type(e).__name__} {resp.text[:200]}"
                        logger.warning("OCR 响应格式异常第 %d/%d 次：%s",
                                       attempt + 1, retries + 1, last_err)
                    else:
                        elapsed_s = time.monotonic() - t0
                        logger.info("OCR 调用成功：model=%s 耗时 %.2fs", self._model, elapsed_s)
                        return content
                if 400 <= status < 500 and status not in (408, 429):
                    raise OCRError(f"OCR 调用不可重试：HTTP {status} {resp.text[:200]}")
                last_err = f"HTTP {status}: {resp.text[:200]}"
                logger.warning("OCR 调用第 %d/%d 次失败：%s", attempt + 1, retries + 1, last_err)
            except (httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError) as e:
                last_err = f"{type(e).__name__}: {e}"
                logger.warning("OCR 网络错第 %d/%d 次：%s", attempt + 1, retries + 1, last_err)
            if attempt < retries:
                await time.sleep(backoff.delay_for(attempt))
        raise OCRError(f"OCR 调用 {retries + 1} 次仍失败：{last_err}")

    async def recognize(self, image_bytes: bytes, prompt: str = OCR_PROMPT) -> str:
        """调用视觉模型识别名片图片，返回提取的文本。"""
        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": _image_to_data_url(image_bytes)},
                        },
                    ],
                }
            ],
            "temperature": 0.1,
        }
        return await self._request(body, retries=1)

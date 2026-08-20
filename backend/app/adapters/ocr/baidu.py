"""百度 OCR（Access Token 模式）。

access_token 获取方式：
1. 手动：https://console.bce.baidu.com/ → 产品服务 → 文字识别 → 创建一个应用，
   应用详情页有 API Key 和 Secret Key，用 https://aikang.baidu.com/tools 里的
   「获取 Access Token」工具生成一个长期有效 token。
2. 代码自动刷新：提供 ocr.api_key（API Key）+ ocr.secret_key（Secret Key），
   provider 启动时自动换取 access_token，以后每 29 天自动刷新。

OCR 接口文档：https://cloud.baidu.com/doc/OCRAPI.html
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Optional

import httpx

from app.adapters.ocr.base import OCRError, OCRProvider

logger = logging.getLogger(__name__)

# access_token 有效期（秒），提前 1 天刷新
_TOKEN_EXPIRES_IN = 29 * 24 * 3600
_TOKEN_REFRESH_AHEAD = 24 * 3600


class BaiduOCRProvider(OCRProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        secret_key: str = "",
        timeout_s: float = 30.0,
    ) -> None:
        # base_url: "https://aip.baidubce.com"
        # api_key: 百度 API Key（用于自动换取 access_token），或直接传已获得的 access_token
        # secret_key: 百度 Secret Key（用于自动刷新 access_token），留空则 api_key 当 access_token 直接用
        self._base_url = (base_url or "https://aip.baidubce.com").rstrip("/")
        self._api_key = api_key          # 百度 API Key
        self._secret_key = secret_key    # 百度 Secret Key（可空）
        self._model = model              # 如 "general_basic"
        self._timeout = httpx.Timeout(pool=5.0, connect=10.0, write=10.0, read=timeout_s)
        self._client = httpx.AsyncClient(timeout=self._timeout)

        # access_token 缓存
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0  # unix timestamp

        # 若 api_key 看起来已经是 access_token 格式（较长），直接用它
        if self._api_key and len(self._api_key) > 50 and "." not in self._api_key:
            self._access_token = self._api_key
            self._token_expires_at = time.time() + _TOKEN_EXPIRES_IN
            logger.info("Baidu OCR: 直接使用提供的 access_token")

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _ensure_token(self) -> str:
        """确保有有效 access_token，必要时刷新。"""
        now = time.time()
        if self._access_token and now < self._token_expires_at - _TOKEN_REFRESH_AHEAD:
            return self._access_token

        # 需要刷新
        if not self._api_key or not self._secret_key:
            raise OCRError(
                "Baidu OCR 未配置：请提供 ocr.api_key（API Key）和 ocr.secret_key（Secret Key）"
                "以自动换取 access_token，或直接提供已获得的 access_token（较长字符串）。"
            )
        self._access_token = await self._refresh_token()
        self._token_expires_at = time.time() + _TOKEN_EXPIRES_IN
        return self._access_token

    async def _refresh_token(self) -> str:
        """用 API Key + Secret Key 换取 access_token。"""
        url = f"{self._base_url}/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": self._api_key,
            "client_secret": self._secret_key,
        }
        resp = await self._client.post(url, params=params)
        if resp.status_code != 200:
            raise OCRError(f"Baidu access_token 获取失败 HTTP {resp.status_code}：{resp.text}")
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise OCRError(f"Baidu access_token 获取失败（空响应）：{data}")
        logger.info("Baidu OCR: 已刷新 access_token")
        return token

    async def recognize(self, image_bytes: bytes, prompt: str = "") -> str:  # noqa: ARG002
        """调用百度 OCR API 识别名片图片，返回提取的文本。prompt 参数被忽略（百度不支持自定义 prompt）。"""
        token = await self._ensure_token()
        url = f"{self._base_url}/rest/2.0/ocr/v1/{self._model}"
        img_b64 = base64.b64encode(image_bytes).decode("ascii")
        body = {"image": img_b64}
        # 通用票据识别可加 "recognize_granularity": "big" 等参数，这里保持简洁
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = await self._client.post(url, headers=headers, data=body,
                                        params={"access_token": token})
        if resp.status_code != 200:
            raise OCRError(f"百度 OCR 请求失败 HTTP {resp.status_code}：{resp.text}")
        data = resp.json()
        if "error_code" in data:
            raise OCRError(f"百度 OCR 错误 {data.get('error_code')}：{data.get('error_msg', '')}")
        # 百度返回 {"words_result": [{"words": "文本行1"}, ...], "words_result_num": N}
        words = data.get("words_result", [])
        lines = [item.get("words", "") for item in words]
        return "\n".join(lines)

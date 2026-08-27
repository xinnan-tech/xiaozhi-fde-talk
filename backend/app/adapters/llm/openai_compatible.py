"""OpenAI 兼容 LLM（/chat/completions）。

- `chat_json`：辅导重算用，`response_format: json_object` + JSON 解析 + 重试
- `chat_text`：报告生成用，纯文本返回（Markdown）+ 重试
- `<think>...</think>` 剥离（适配推理模型）
- 细粒度超时

deepseek / qwen / doubao / glm 等均暴露 OpenAI 兼容端点，换 LLM_BASE_URL+KEY+MODEL 即可。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from app.adapters.llm.base import LLMProvider
from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys
from app.core.retry import BackoffPolicy

# Aliased: LLMError = I18nError. Existing `raise LLMError(...)` and
# `except LLMError` keep working; the localized message comes from Keys.*.
LLMError = I18nError

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# 需要禁用思考模式的平台域名及其对应参数（默认开启关闭）
# THINKING_DISABLED_DOMAINS：按 base_url 域名注入 extra_body
# 让推理模型（如 qwen-plus / deepseek / kimi / glm / doubao 思考模式）跳过思考链，加快响应。
_THINKING_DISABLED_DOMAINS: dict[str, dict[str, Any]] = {
    "aliyuncs.com": {"enable_thinking": False},  # 阿里百炼（qwen）
    "dashscope.aliyuncs.com": {"enable_thinking": False},
    "deepseek.com": {"thinking": {"type": "disabled"}},  # DeepSeek
    "bigmodel.cn": {"thinking": {"type": "disabled"}},  # 智谱 GLM
    "moonshot.cn": {"thinking": {"type": "disabled"}},  # Moonshot Kimi
    "volces.com": {"thinking": {"type": "disabled"}},  # 火山豆包
}

# chat_json 输出上限：辅导清单合法输出实测 509-833 token，取 1.8 倍余量；
# 失控复读时在 1500 处截断 → 抛 LLMError（引擎保留旧清单、限频续算），而不是耗满 read 超时。
_JSON_MAX_TOKENS = 1500


class OpenAILLMProvider(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        llm_timeout_s: float,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key
        self._model = model
        self._llm_timeout_s = float(llm_timeout_s)
        # connect 默认 10s：dashscope.aliyuncs.com 在跨网场景实测 DNS+TCP+TLS 约 4s，
        # 之前的 3s 每次必爆 ConnectTimeout。read 仍走 llm_timeout_s（可配）。
        self._timeout = httpx.Timeout(
            pool=2.0, connect=10.0, write=5.0, read=float(llm_timeout_s)
        )
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._api_key and self._model)

    def _apply_thinking_disabled(self, body: dict) -> None:
        """按 base_url 域名注入禁用思考的 extra_body（in-place 修改 body）。

        推理模型默认会先输出 <think>...</think> 再出正文，徒增首字延迟与 token 成本；
        多数 OpenAI 兼容平台支持在 extra_body 关闭，详见模块级 _THINKING_DISABLED_DOMAINS。
        """
        try:
            domain = urlparse(self._base_url).netloc
        except ValueError:
            return
        for disabled_domain, params in _THINKING_DISABLED_DOMAINS.items():
            if disabled_domain in domain:
                body.setdefault("extra_body", {}).update(params)
                logger.info("LLM 禁用思考模式：域名=%s 参数=%s", domain, params)
                return

    async def _request(self, body: dict, retries: int) -> str:
        """POST chat/completions，返回去 think 后的 content 文本。

        按 status 分类重试：4xx（除 408/429）不可重试，立即抛；5xx / 429 / 408 /
        网络错走 BackoffPolicy 指数退避。
        """
        if not self.configured:
            raise LLMError(Keys.LLM_NOT_CONFIGURED, http_status=502)
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
                        content = _THINK_RE.sub("", content).strip()
                    except (ValueError, KeyError, IndexError, TypeError) as e:
                        # 200 但载荷非标准（网关错误页 / 限流提示 / 字段格式变更）：
                        # 与 5xx 同等对待，走退避重试；重试耗尽由循环尾统一抛 LLMError。
                        last_err = f"响应非标准格式: {type(e).__name__} {resp.text[:200]}"
                        logger.warning("LLM 响应格式异常第 %d/%d 次：%s",
                                       attempt + 1, retries + 1, last_err)
                    else:
                        elapsed_s = time.monotonic() - t0
                        usage = data.get("usage") or {}
                        prompt = usage.get("prompt_tokens", "?")
                        completion = usage.get("completion_tokens", "?")
                        total = usage.get("total_tokens", "?")
                        logger.info(
                            "LLM 调用成功：model=%s 耗时 %.2fs 输入 %s token / 输出 %s token / 共 %s token",
                            self._model, elapsed_s, prompt, completion, total,
                        )
                        return content
                # 4xx（除 408/429）：不可重试
                if 400 <= status < 500 and status not in (408, 429):
                    raise LLMError(
                        Keys.LLM_NON_RETRYABLE, http_status=502,
                        status=status, body=resp.text[:200],
                    )
                # 5xx / 429 / 408：可重试
                last_err = f"HTTP {status}: {resp.text[:200]}"
                logger.warning("LLM 调用第 %d/%d 次失败：%s", attempt + 1, retries + 1, last_err)
            except (httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError) as e:
                # 网络错：可重试
                last_err = f"{type(e).__name__}: {e}"
                logger.warning("LLM 网络错第 %d/%d 次：%s", attempt + 1, retries + 1, last_err)
            if attempt < retries:
                await asyncio.sleep(backoff.delay_for(attempt))
        raise LLMError(
            Keys.LLM_RETRY_EXHAUSTED, http_status=502,
            retries=retries + 1, last_err=last_err,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_json(
        self,
        system: str,
        user: str,
        retries: int = 2,
        output_schema: Optional[type[BaseModel]] = None,
    ) -> dict[str, Any]:
        """辅导重算用：强制 json_object，返回解析后的 dict。

        catch JSONDecodeError → LLMError；可选 pydantic schema 校验。
        """
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
            "max_tokens": _JSON_MAX_TOKENS,
        }
        self._apply_thinking_disabled(body)
        content = await self._request(body, retries)
        fence = re.search(r"\{.*\}", content, re.DOTALL)
        if fence is None:
            raise LLMError(
                Keys.LLM_NO_JSON_BLOCK, http_status=502,
                snippet=content[:200],
            )
        json_str = fence.group(0)
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise LLMError(
                Keys.LLM_INVALID_JSON, http_status=502,
                err=str(e), json_str=json_str[:200],
            ) from e
        if output_schema is not None:
            try:
                output_schema.model_validate(parsed)
            except Exception as e:  # noqa: BLE001
                raise LLMError(
                    Keys.LLM_SCHEMA_MISMATCH, http_status=502,
                    err=str(e), json_str=json_str[:200],
                ) from e
        return parsed

    async def chat_text(
        self,
        system: str,
        user: str,
        retries: int = 2,
        json_mode: bool = False,
    ) -> str:
        """返回原始文本（Markdown 或 JSON 字符串），由调用方解析。

        json_mode=True：带 response_format=json_object + temperature=0.3 +
        max_tokens=_JSON_MAX_TOKENS 三件套，请求服务端强制 JSON 输出；同时返回
        raw text 供调用方跑脚本检测 / fence 解析。chat_json 路径被此形参替代——
        旧 chat_json 保留以备兼容，但生产路径（coaching）改走 chat_text(...,json_mode=True)。

        json_mode=False：纯文本（默认，报告生成用）。
        """
        body: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
            body["temperature"] = 0.3
            body["max_tokens"] = _JSON_MAX_TOKENS
        else:
            body["temperature"] = 0.4
        self._apply_thinking_disabled(body)
        # 外层总预算：跨所有重试 + 退避，避免 LLM 半挂拖住报告生成
        budget = self._llm_timeout_s * (retries + 1) * 1.5
        try:
            return await asyncio.wait_for(self._request(body, retries), timeout=budget)
        except asyncio.TimeoutError as e:
            raise LLMError(Keys.LLM_TIMEOUT, http_status=504, budget=budget) from e

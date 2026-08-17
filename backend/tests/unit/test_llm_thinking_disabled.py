""" LLM 禁用思考模式：按 base_url 域名注入 extra_body。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.adapters.llm.openai_compatible import (
    OpenAILLMProvider,
    _THINKING_DISABLED_DOMAINS,
)


def _make_provider(base_url: str) -> OpenAILLMProvider:
    return OpenAILLMProvider(
        base_url=base_url,
        api_key="test-key",
        model="test-model",
        llm_timeout_s=10.0,
    )


# --- 直接调方法（不发起请求）---

@pytest.mark.parametrize(
    "base_url, expected_key",
    [
        ("https://dashscope.aliyuncs.com/v1", "enable_thinking"),
        ("https://api.deepseek.com/v1", "thinking"),
        ("https://open.bigmodel.cn/api/paas/v4", "thinking"),
        ("https://api.moonshot.cn/v1", "thinking"),
        ("https://ark.cn-beijing.volces.com/api/v3", "thinking"),
    ],
)
def test_apply_thinking_disabled_injects_extra_body(base_url: str, expected_key: str):
    provider = _make_provider(base_url)
    body: dict = {}
    provider._apply_thinking_disabled(body)
    assert "extra_body" in body
    assert expected_key in body["extra_body"]
    # 关闭值要么是 False（aliyun），要么是 dict(type=disabled)（其他家）
    assert body["extra_body"][expected_key] in (False, {"type": "disabled"})


def test_no_match_leaves_body_untouched():
    provider = _make_provider("https://api.openai.com/v1")
    body: dict = {"model": "gpt-4"}
    provider._apply_thinking_disabled(body)
    assert "extra_body" not in body
    assert body == {"model": "gpt-4"}


def test_invalid_base_url_does_not_raise():
    """畸形 base_url 不抛错，跳过注入。"""
    provider = _make_provider("")  # 空串 urlparse 不抛但 netloc 为空
    body: dict = {}
    provider._apply_thinking_disabled(body)
    assert "extra_body" not in body


def test_module_map_covers_xiaozhi_providers():
    """守住与小智 openai.py 的同步：小智 5 个域名我们都覆盖。"""
    assert set(_THINKING_DISABLED_DOMAINS.keys()) >= {
        "aliyuncs.com",
        "deepseek.com",
        "bigmodel.cn",
        "moonshot.cn",
        "volces.com",
    }


# --- 端到端：chat_json / chat_text 的 body 被正确注入 ---

def _ok_response(content: str = "ok") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json = MagicMock(return_value={"choices": [{"message": {"content": content}}]})
    return resp


@pytest.mark.asyncio
async def test_chat_json_injects_disable_for_qwen():
    """chat_json 走 dashscope → body 带 enable_thinking=False。"""
    provider = _make_provider("https://dashscope.aliyuncs.com/v1")
    captured: dict = {}

    async def _post(*_args, **kwargs):  # noqa: ARG004
        captured.update(kwargs["json"])
        return _ok_response(content='{"x":1}')

    provider._client.post = AsyncMock(side_effect=_post)

    await provider.chat_json("sys", "usr")

    assert captured["extra_body"]["enable_thinking"] is False
    # 业务字段不被破坏
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["temperature"] == 0.3


@pytest.mark.asyncio
async def test_chat_text_injects_disable_for_deepseek():
    """chat_text 走 deepseek → body 带 thinking.type=disabled。"""
    provider = _make_provider("https://api.deepseek.com/v1")
    captured: dict = {}

    async def _post(*_args, **kwargs):  # noqa: ARG004
        captured.update(kwargs["json"])
        return _ok_response()

    provider._client.post = AsyncMock(side_effect=_post)

    await provider.chat_text("sys", "usr")

    assert captured["extra_body"]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_chat_json_openai_does_not_inject():
    """非国内平台 → 不注入 extra_body（OpenAI 官方无对应参数，注入会污染请求）。"""
    provider = _make_provider("https://api.openai.com/v1")
    captured: dict = {}

    async def _post(*_args, **kwargs):  # noqa: ARG004
        captured.update(kwargs["json"])
        return _ok_response(content='{"x":1}')

    provider._client.post = AsyncMock(side_effect=_post)

    await provider.chat_json("sys", "usr")

    assert "extra_body" not in captured
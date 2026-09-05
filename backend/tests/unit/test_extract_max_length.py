"""issue #207：/api/v1/interviews/extract 的 transcript 防御。

三道防线：
1. schema 层 `max_length=200_000` —— 超长请求 422，FastAPI 默认走 pydantic
   validation 处理器翻译为 `validation.string_too_long`（所有 locale 都有翻译）
2. OpenAI 兼容 LLM adapter 的 `_request` 在 4xx 时检测 context overflow
   标记（`context_length_exceeded` / `Range of input length` / `maximum
   context length` 等），命中则抛 `LLMContextOverflowError`（422）而非通用
   `LLM_NON_RETRYABLE`（502）
3. /extract 路由 `except LLMContextOverflowError: raise` 让 422 透传给前端
   （而不是被 except LLMError 静默 fallback 成 current_values），让用户区分
   「请缩短 transcript」与「重试」

测试覆盖：
- schema：boundary（200_000 通过 / 200_001 拒） + 端到端 422
- adapter：marker 命中 + 4xx 路径
- route：context overflow → 422（不被静默吞）；其它 LLMError → 保留 current_values
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.llm.base import LLMContextOverflowError
from app.adapters.llm.openai_compatible import OpenAILLMProvider, _is_context_overflow
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user
from app.transport.http.schemas import ExtractRequest


# ---------- schema 层（pydantic max_length）----------

TRANSCRIPT_MAX = 200_000


def test_extract_request_accepts_transcript_at_max_length():
    """200_000 字符（恰好等于上限）应通过 schema 校验。"""
    req = ExtractRequest(
        transcript="x" * TRANSCRIPT_MAX,
        template_id="pm-research",
        fields=["objective"],
    )
    assert len(req.transcript) == TRANSCRIPT_MAX


def test_extract_request_rejects_transcript_over_max_length():
    """200_001 字符（超 1 字节）应被 pydantic 拒为 422。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as ei:
        ExtractRequest(
            transcript="x" * (TRANSCRIPT_MAX + 1),
            template_id="pm-research",
            fields=["objective"],
        )
    err = ei.value.errors()[0]
    assert err["type"] == "string_too_long"
    assert err["loc"] == ("transcript",)
    assert err["ctx"]["max_length"] == TRANSCRIPT_MAX


# ---------- adapter 层（_is_context_overflow marker）----------

@pytest.mark.parametrize("body", [
    # OpenAI / Doubao / DeepSeek
    '{"error":{"code":"context_length_exceeded","message":"..."}}',
    "This model's maximum context length is 128000 tokens",
    # DashScope（qwen / 通义百炼）
    "Range of input length should be [1, 30720] (50000 > 30720)",
    # 兼容大小写
    "CONTEXT_LENGTH_EXCEEDED",
    # 部分国内平台
    "context length is too long",
])
def test_is_context_overflow_positive(body: str):
    assert _is_context_overflow(body) is True, body


@pytest.mark.parametrize("body", [
    "",  # 空 body
    "{}",
    '{"error":{"code":"invalid_api_key","message":"bad key"}}',
    "Rate limit exceeded",
    "Internal server error",
    '{"error":{"type":"invalid_request_error","code":"missing_parameter"}}',
])
def test_is_context_overflow_negative(body: str):
    assert _is_context_overflow(body) is False, body


@pytest.mark.asyncio
async def test_adapter_maps_context_overflow_after_response_prefix_to_422():
    """Adapter must inspect the complete 4xx body before truncating diagnostics."""
    provider = OpenAILLMProvider(
        base_url="https://example.com",
        api_key="test-key",
        model="test-model",
        llm_timeout_s=10.0,
    )
    response = MagicMock(spec=httpx.Response)
    response.status_code = 400
    response.text = "x" * 240 + '{"error":{"code":"context_length_exceeded"}}'
    provider._client.post = AsyncMock(return_value=response)

    with pytest.raises(LLMContextOverflowError) as ei:
        await provider._request({"model": "test-model"}, retries=0)

    assert ei.value.http_status == 422
    assert ei.value.params["status"] == 400


# ---------- 端到端：HTTP 422 + locale 文案 ----------

@pytest.fixture
def extract_client():
    """TestClient + get_current_user override：与 test_extract_endpoint_i18n 同款。"""
    from app.app import create_app

    app = create_app()

    async def _fake_user() -> CurrentUser:
        return CurrentUser(user_id="issue-207-user", username="user", role="user")

    app.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app)


def _post_extract(client, transcript: str = "客户是 ABC 公司 CEO 张三", fields: list[str] | None = None):
    return client.post(
        "/api/v1/interviews/extract",
        json={
            "transcript": transcript,
            "template_id": "pm-research",
            "fields": fields or ["objective"],
            "field_labels": {"objective": "目标"},
            "field_types": {"objective": "text"},
            "current_values": {"objective": "已有值"},
        },
    )


def test_extract_transcript_over_max_returns_422_zh_cn(extract_client):
    """transcript 超 200_000 → 422 + `validation.string_too_long` 文案（zh_CN 默认）。

    之前 schema 无 max_length：5MB 字符串直接灌进 LLM prompt，被 service
    层 fallback 成 current_values，前端拿 200 + 空结果以为是「LLM 抽不出来」
    （issue #207）。
    """
    r = _post_extract(extract_client, transcript="x" * (TRANSCRIPT_MAX + 1))
    assert r.status_code == 422, r.text
    body = r.json()
    # FastAPI `_validation_handler` 把 pydantic 错误转译为 i18n 字符串 + type/loc
    assert "detail" in body and isinstance(body["detail"], list)
    err = body["detail"][0]
    assert err["type"] == "string_too_long"
    assert err["loc"] == ["body", "transcript"]  # body 包了请求体
    assert str(TRANSCRIPT_MAX) in err["msg"], err


def test_extract_transcript_at_max_passes_schema(extract_client):
    """transcript 正好 200_000 → 通过 schema 校验（边界值）。"""
    from unittest.mock import MagicMock

    async def fake_chat_json(system, user):
        return {"objective": "测试值"}

    fake_store = MagicMock()

    async def fake_get(key):
        return None

    fake_store.get = fake_get

    with patch("app.adapters.llm.factory.get_llm") as mock_get_llm, \
         patch("app.transport.http.routes.interviews.get_config_store", return_value=fake_store):
        mock_get_llm.return_value.chat_json = fake_chat_json
        r = _post_extract(extract_client, transcript="x" * TRANSCRIPT_MAX)
    assert r.status_code == 200, r.text
    assert r.json()["values"]["objective"] == "测试值"


def test_extract_context_overflow_returns_422_not_silent_fallback(extract_client):
    """LLM 抛 LLMContextOverflowError → 路由层 re-raise → 422 + i18n 文案。

    之前路由层只 `except LLMError` 把任何 LLM 错都 fallback 成 current_values
    ——5MB transcript 让 LLM 拒掉后用户看到「抽不出来」不断重试（issue #207）。
    现拆出 context overflow 单独 re-raise，前端能定位到「文本太长」。
    """
    from unittest.mock import MagicMock

    fake_store = MagicMock()

    async def fake_get(key):
        return None

    fake_store.get = fake_get

    async def fake_chat_json(system, user):
        raise LLMContextOverflowError(
            status=400,
            snippet="context_length_exceeded: input too long",
        )

    with patch("app.adapters.llm.factory.get_llm") as mock_get_llm, \
         patch("app.transport.http.routes.interviews.get_config_store", return_value=fake_store):
        mock_get_llm.return_value.chat_json = fake_chat_json
        r = _post_extract(extract_client, transcript="正常长度" * 100)

    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == Keys.LLM_CONTEXT_OVERFLOW.value, body
    # zh_CN 默认 locale
    assert "超出" in body["detail"] or "上限" in body["detail"], body
    # 关键：不是 200 + current_values 兜底
    assert r.status_code != 200


def test_extract_other_llm_error_still_falls_back_to_current_values(extract_client):
    """其他 LLMError（非 context overflow）仍保留 current_values 兜底 —— 行为不变。

    只 context overflow 单独 re-raise，其它错误（鉴权失败 / 服务挂 / JSON
    解析失败）仍走原 fallback 路径，避免破坏 LLM 临时抖动的恢复体验。
    """
    from unittest.mock import MagicMock

    fake_store = MagicMock()

    async def fake_get(key):
        return None

    fake_store.get = fake_get

    async def fake_chat_json(system, user):
        # 非 context overflow 的 LLM 错误（鉴权失败 / 服务挂 / JSON 解析失败等）——
        # 走 LLM_NON_RETRYABLE（502）。路由层应保留 current_values 兜底，不透传给用户。
        raise I18nError(
            Keys.LLM_NON_RETRYABLE.value, http_status=502,
            status=500, body="internal error",
        )

    with patch("app.adapters.llm.factory.get_llm") as mock_get_llm, \
         patch("app.transport.http.routes.interviews.get_config_store", return_value=fake_store):
        mock_get_llm.return_value.chat_json = fake_chat_json
        r = _post_extract(extract_client, transcript="正常长度" * 100)

    assert r.status_code == 200, r.text
    body = r.json()
    # current_values 兜底：保留「已有值」
    assert body["values"]["objective"] == "已有值", body

"""OCR adapter 错误 → I18nError 映射单测。

验证 provider 实现层抛出的异常：
- 类型是 I18nError（含 OCRError 别名兼容）
- http_status 正确（502）
- code 落在 Keys.OCR_* 命名空间
- detail 经 t() 翻译后含中文
"""
from __future__ import annotations

import pytest

from app.core.i18n import t
from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys


def test_ocrerror_is_i18nerror_alias():
    """OCRError 必须是 I18nError 子类，兼容 raise/except 旧写法。"""
    from app.adapters.ocr.base import OCRError
    assert issubclass(OCRError, I18nError)
    assert OCRError is I18nError


async def test_openai_unconfigured_raises_i18nerror():
    """OpenAI provider 未配置 → I18nError(Keys.OCR_NOT_CONFIGURED, 502)。"""
    from app.adapters.ocr.openai_compatible import OpenAICompatibleOCRProvider

    p = OpenAICompatibleOCRProvider(base_url="", api_key="", model="")
    assert p.configured is False
    with pytest.raises(I18nError) as ei:
        await p._request(body={}, retries=0)
    assert ei.value.http_status == 502
    assert ei.value.code == Keys.OCR_NOT_CONFIGURED.value
    # detail 经翻译必须是中文
    detail = ei.value.localized(locale="zh-CN")
    assert "未配置" in detail


async def test_openai_non_retryable_raises_i18nerror(monkeypatch):
    """OpenAI provider 4xx 不可重试 → I18nError(Keys.OCR_INVOKE_FAILED, 502)。"""
    from app.adapters.ocr import openai_compatible as oai

    class _FakeResp:
        status_code = 400
        text = "bad request body"
        def json(self): return {}

    class _FakeClient:
        async def post(self, *a, **kw): return _FakeResp()

    p = oai.OpenAICompatibleOCRProvider(base_url="https://x", api_key="k", model="m")
    p._client = _FakeClient()
    with pytest.raises(I18nError) as ei:
        await p._request(body={}, retries=0)
    assert ei.value.http_status == 502
    assert ei.value.code == Keys.OCR_INVOKE_FAILED.value
    assert "HTTP 400" in ei.value.localized(locale="zh-CN")


async def test_openai_retry_exhausted_raises_i18nerror(monkeypatch):
    """OpenAI provider 网络错重试耗尽 → I18nError(Keys.OCR_INVOKE_FAILED, 502, err=...)。"""
    from app.adapters.ocr import openai_compatible as oai
    import httpx

    class _FakeClient:
        async def post(self, *a, **kw):
            raise httpx.ConnectError("conn refused")

    p = oai.OpenAICompatibleOCRProvider(base_url="https://x", api_key="k", model="m")
    p._client = _FakeClient()
    with pytest.raises(I18nError) as ei:
        await p._request(body={}, retries=1)
    assert ei.value.http_status == 502
    assert ei.value.code == Keys.OCR_INVOKE_FAILED.value
    detail = ei.value.localized(locale="zh-CN")
    assert "OCR 调用失败" in detail or "调用失败" in detail


async def test_baidu_no_secret_key_raises_i18nerror():
    """Baidu provider 缺 secret_key 且 api_key 不像 access_token → I18nError。"""
    from app.adapters.ocr.baidu import BaiduOCRProvider

    p = BaiduOCRProvider(base_url="https://aip.baidubce.com", api_key="short", model="general_basic")
    with pytest.raises(I18nError) as ei:
        await p._ensure_token()
    assert ei.value.http_status == 502
    assert ei.value.code == Keys.OCR_NOT_CONFIGURED.value
"""Doubao Seed ASR 2.0 API-Key protocol contract."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _provider(api_key: str = "ak-test"):
    store = MagicMock()
    values = {
        "asr.doubao_stream.api_key": api_key,
        "asr.doubao_stream.resource_id": "volc.seedasr.sauc.duration",
        "asr.doubao_stream.enable_multilingual": "false",
    }
    store.get_sync.side_effect = lambda key, default=None: values.get(key, default)
    with patch("app.adapters.asr.doubao_stream.get_config_store", return_value=store):
        from app.adapters.asr.doubao_stream import DoubaoStreamProvider

        return DoubaoStreamProvider()


def test_doubao_uses_api_key_headers_and_seed_resource():
    provider = _provider()
    headers = provider._api_key_auth()

    assert headers["X-Api-Key"] == "ak-test"
    assert headers["X-Api-Resource-Id"] == "volc.seedasr.sauc.duration"
    # X-Api-Request-Id 必须是合法 UUID 格式（服务端用它幂等去重）；str(uuid.uuid4())
    # 永远非空，原来的 `assert headers["X-Api-Request-Id"]` 是空断言。
    uuid.UUID(headers["X-Api-Request-Id"])
    assert "X-Api-App-Key" not in headers
    assert "X-Api-Access-Key" not in headers


def test_doubao_init_payload_does_not_use_legacy_token():
    provider = _provider()
    payload = provider._construct_request("req-1")

    assert payload["request"]["model_name"] == "bigmodel"
    assert payload["request"]["end_window_size"] == 800
    assert payload["audio"]["codec"] == "raw"
    assert "app" not in payload


@pytest.mark.asyncio
async def test_doubao_start_stream_raises_when_api_key_missing():
    """P2-4: cache miss / DB 空 api_key 时 start_stream 必须 fail-fast 抛
    ValueError，避免后续 websockets.connect 用空 key 走到服务端再被 401 拒。

    provider.__init__ 已把 _api_key 兜底成 ""（cache miss + or ""），
    start_stream 必须显式校验并抛带「api_key 未配置」字样的 ValueError。
    """
    provider = _provider(api_key="")
    with pytest.raises(ValueError, match="api_key 未配置"):
        await provider.start_stream(on_utterance=AsyncMock())

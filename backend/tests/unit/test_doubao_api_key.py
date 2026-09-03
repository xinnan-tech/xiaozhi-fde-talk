"""Doubao Seed ASR 2.0 API-Key protocol contract."""
from unittest.mock import MagicMock, patch


def _provider():
    store = MagicMock()
    values = {
        "asr.doubao_stream.api_key": "ak-test",
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
    assert headers["X-Api-Request-Id"]
    assert "X-Api-App-Key" not in headers
    assert "X-Api-Access-Key" not in headers


def test_doubao_init_payload_does_not_use_legacy_token():
    provider = _provider()
    payload = provider._construct_request("req-1")

    assert payload["request"]["model_name"] == "bigmodel"
    assert payload["request"]["end_window_size"] == 800
    assert payload["audio"]["codec"] == "raw"
    assert "app" not in payload

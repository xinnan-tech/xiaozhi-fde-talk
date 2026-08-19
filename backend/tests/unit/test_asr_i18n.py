# tests/unit/test_asr_i18n.py
import pytest
from app.adapters.asr.funasr_server import ASRProviderError
from app.core.i18n.messages import Keys


def test_asr_provider_error_carries_keys():
    with pytest.raises(ASRProviderError) as ei:
        raise ASRProviderError(
            Keys.ASR_CONNECT_FAIL, http_status=502,
            ws_url="ws://x", reason="connect refused",
        )
    assert ei.value.code == "asr.connect_fail"
    assert ei.value.params["reason"] == "connect refused"


def test_asr_dead_key_only():
    with pytest.raises(ASRProviderError) as ei:
        raise ASRProviderError(Keys.ASR_DEAD, http_status=502)
    assert ei.value.code == "asr.dead"
    assert ei.value.localized(locale="en-US") == "ASR connection dropped (funasr dead)"

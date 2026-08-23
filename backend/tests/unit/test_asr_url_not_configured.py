"""FunASRServerProvider 在 asr.ws_url 未配置时显式抛 i18n 错误（502）。

背景：以前 line 114 有 ``or "wss://localhost:10096"`` 兜底，导致 prod 没配 ASR 时
静默连 localhost 失败、错误延迟到 502 才发现。删除兜底后，未配时 start_stream
直接抛 ASRProviderError(ASR_URL_NOT_CONFIGURED, http_status=502)——
与同文件 ASR_DEAD / ASR_CONNECT_FAIL 同款，handler 现有 except 自动接住。
"""
from unittest.mock import MagicMock, patch

import pytest

from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys


def _make_provider_with_ws_url(ws_url: str):
    """构造一个不连真 WS 的 provider，注入 asr.ws_url = ws_url。"""
    with patch("app.adapters.asr.funasr_server.get_config_store") as gcs:
        store = MagicMock()
        store.get_sync.side_effect = lambda k, default="": {
            "asr.ws_url": ws_url,
            "asr.sample_rate": "16000",
            "asr.language": "zh",
        }.get(k, default)
        gcs.return_value = store
        from app.adapters.asr.funasr_server import FunASRServerProvider
        return FunASRServerProvider()


@pytest.mark.asyncio
async def test_start_stream_raises_i18n_when_ws_url_empty():
    """asr.ws_url 显式为空 → ASRProviderError(ASR_URL_NOT_CONFIGURED, 502)。"""
    p = _make_provider_with_ws_url("")
    assert p._ws_url == "", "不应当再被替换为 localhost 兜底"
    with pytest.raises(I18nError) as exc_info:
        await p.start_stream(_noop_utterance)
    err = exc_info.value
    assert err.code == Keys.ASR_URL_NOT_CONFIGURED.value
    assert err.http_status == 502


@pytest.mark.asyncio
async def test_start_stream_raises_i18n_when_ws_url_whitespace_only():
    """asr.ws_url 全空白（DB 被写入 "   "）→ 同款报错。"""
    p = _make_provider_with_ws_url("   ")
    assert p._ws_url == "   "
    with pytest.raises(I18nError) as exc_info:
        await p.start_stream(_noop_utterance)
    assert exc_info.value.code == Keys.ASR_URL_NOT_CONFIGURED.value


async def _noop_utterance(_text: str, _is_final: bool) -> None:
    """占位回调；start_stream 应在校验 ws_url 阶段就抛，不会调到回调。"""

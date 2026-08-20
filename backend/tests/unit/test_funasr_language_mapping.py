"""asr.language（zh/yue/en）→ FunASR init_msg 合法值映射。"""
from unittest.mock import MagicMock, patch


def _make_provider(config_value: str):
    """构造一个不连真 WS 的 FunASRServerProvider，注入 config 值。"""
    with patch("app.adapters.asr.funasr_server.get_config_store") as gcs:
        store = MagicMock()
        store.get_sync.side_effect = lambda k, default="": {
            "asr.ws_url": "wss://localhost:10096",
            "asr.sample_rate": "16000",
            "asr.ws_verify_ssl": "false",
            "asr.language": config_value,
        }.get(k, default)
        gcs.return_value = store
        from app.adapters.asr.funasr_server import FunASRServerProvider
        return FunASRServerProvider()


def test_zh_passes_through():
    p = _make_provider("zh")
    assert p._funasr_language == "zh"


def test_yue_passes_through():
    p = _make_provider("yue")
    assert p._funasr_language == "yue"


def test_en_passes_through():
    p = _make_provider("en")
    assert p._funasr_language == "en"


def test_empty_string_omits_language():
    p = _make_provider("")
    assert p._funasr_language == ""


def test_fun_asr_legal_but_not_in_our_enum_falls_back_to_auto():
    """Defensive: FunASR-legal 但不在我们 enum 的值（如 ja, ko）→ 回退到「不传」
    而非抛——init_msg 整段崩掉会让 ASR 整场不出字。"""
    p = _make_provider("ja")
    assert p._funasr_language == ""
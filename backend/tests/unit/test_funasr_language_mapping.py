"""asr.language（zh_cn/zh_tw/en）→ FunASR init_msg 合法值映射。"""
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


def test_zh_cn_maps_to_zh():
    p = _make_provider("zh_cn")
    assert p._funasr_language == "zh"


def test_zh_tw_maps_to_zh():
    p = _make_provider("zh_tw")
    assert p._funasr_language == "zh"


def test_en_passthrough():
    p = _make_provider("en")
    assert p._funasr_language == "en"


def test_empty_string_omits_language():
    p = _make_provider("")
    assert p._funasr_language == ""


def test_unsupported_value_omits_language():
    """Defensive: 不在映射表的字符串（不一定是 FunASR 不合法）→ 回退到「不传」
    而非抛——init_msg 整段崩掉会让 ASR 整场不出字。FunASR 自身合法的 ja/ko 等
    不在我们的 enum，运行时遇到也应静默走自动检测。"""
    p = _make_provider("xx")  # 完全乱字符——既不在我们 enum，也不在 FunASR 合法集
    assert p._funasr_language == ""

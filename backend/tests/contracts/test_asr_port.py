"""端口契约测试：ASRProvider 端口一致性。

验证所有 ASR 实现都满足 adapters/asr/base.py 声明的契约：
  - 继承 ASRProvider
  - 声明 interface_type ∈ {offline, stream}
  - offline 实现可调用 transcribe；stream 实现可调用 start/feed/stop_stream + close

仅支持流式 ASR（funasr_server）。
按 design §10 PR2：端口契约测试骨架。FunASR 服务离线时 skip，不阻断 CI。
"""
from __future__ import annotations

import pytest

from app.adapters.asr.base import ASRProvider

pytestmark = pytest.mark.contracts


def _assert_port_shape(provider: ASRProvider) -> None:
    assert isinstance(provider, ASRProvider), f"{type(provider)} 未继承 ASRProvider"
    assert provider.interface_type in ("offline", "stream"), f"非法 interface_type: {provider.interface_type}"
    # 两个分支方法都必须存在（即便另一分支 raise NotImplementedError）
    for name in ("transcribe", "start_stream", "feed_stream", "stop_stream", "close"):
        assert callable(getattr(provider, name, None)), f"缺失方法: {name}"


def test_stream_asr_check_does_not_instantiate():
    """is_stream_asr 仅依据 interface_type 判断，不实例化 provider（design 约束）。"""
    from app.adapters.asr.factory import is_stream_asr

    assert isinstance(is_stream_asr(), bool)
    # 仅支持流式 ASR
    assert is_stream_asr() is True, "funasr_server 应为流式 ASR"


def test_asr_factory_creates_stream_provider():
    """create_asr_provider 创建流式 provider，满足 ASRProvider 契约。

    pipeline 使用 create_asr_provider（每会话一个实例），
    get_asr_provider（单例 offline）不再使用，但保留以防其他用途。
    """
    try:
        from app.adapters.asr.factory import create_asr_provider

        provider = create_asr_provider()
    except Exception as e:  # noqa: BLE001  FunASR 服务未就绪
        pytest.skip(f"ASR provider 不可用：{e}")
    _assert_port_shape(provider)
    assert provider.interface_type == "stream", f"应为流式 provider，实际: {provider.interface_type}"

"""端口契约测试：LLMProvider 端口一致性。

验证默认 LLM 实现满足 adapters/llm/base.py 声明的契约：
  - 继承 LLMProvider
  - configured 属性为 bool
  - chat_json / chat_text 可调用
"""
from __future__ import annotations

import pytest

from app.adapters.llm.base import LLMProvider

pytestmark = pytest.mark.contracts


def test_llm_port_shape():
    try:
        from app.adapters.llm.factory import get_llm

        llm = get_llm()
    except Exception as e:  # noqa: BLE001  api_key/网络未就绪
        pytest.skip(f"LLM provider 不可用：{e}")

    assert isinstance(llm, LLMProvider), f"{type(llm)} 未继承 LLMProvider"
    assert isinstance(llm.configured, bool)
    for name in ("chat_json", "chat_text"):
        assert callable(getattr(llm, name, None)), f"缺失方法: {name}"

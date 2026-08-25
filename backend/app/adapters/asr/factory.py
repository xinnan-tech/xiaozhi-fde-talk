"""ASR 工厂：按 asr_type 创建 provider（可插拔）。

type → module.class 注册，懒加载：模型重，只在首次用时加载。
"""
from __future__ import annotations

import importlib
import os
from typing import Optional

from app.adapters.asr.base import ASRProvider
from app.core.config_store import DEFAULTS, get_config_store

# asr_type → (模块, 类名)
_REGISTRY = {
    "funasr_server": ("app.adapters.asr.funasr_server", "FunASRServerProvider"),
    "funasr_mock": ("app.adapters.asr.funasr_mock", "FunASRMockProvider"),
    "doubao_stream": ("app.adapters.asr.doubao_stream", "DoubaoStreamProvider"),
}

_provider: Optional[ASRProvider] = None


def _read_asr_config() -> dict[str, object]:
    """从 ConfigStore 同步读 ASR 配置（warm 已预热）；缺则用 DEFAULTS。

    env 优先级（仅覆盖 type）：
      - 形如 ``ASR_TYPE`` 的环境变量会覆盖 DB / DEFAULTS 的 ``asr.type``。
      - 设计目的：e2e/手动 mock 切换只需注一个 env var，不动 DB。
      - 不覆盖 sample_rate / ws_url —— 那些属于运行时域配置，DB 才是单一来源。
    """
    store = get_config_store()
    def _g(key: str, cast=str, default=None):
        raw = store.get_sync(key, DEFAULTS.get(key, default if default is not None else ""))
        if raw is None or raw == "":
            return default if default is not None else ""
        return cast(raw)
    asr_type = os.environ.get("ASR_TYPE", "").strip() or _g("asr.type", str, "funasr_server")
    return {
        "type": asr_type,
        "sample_rate": _g("asr.sample_rate", int, 16000),
        "ws_url": _g("asr.ws_url", str, ""),
    }


def create_asr_provider() -> ASRProvider:
    """从 ConfigStore 同步读 ASR 配置 + 构造 provider。"""
    cfg = _read_asr_config()
    asr_type = cfg["type"]
    if asr_type not in _REGISTRY:
        raise ValueError(f"未知 ASR_TYPE={asr_type}，可选: {list(_REGISTRY)}")
    module_path, class_name = _REGISTRY[asr_type]
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def get_asr_provider() -> ASRProvider:
    """单例（懒加载）。仅用于非流式 provider。"""
    global _provider
    if _provider is None:
        _provider = create_asr_provider()
    return _provider


def invalidate(changed_keys: set[str]) -> None:
    """ConfigStore 订阅钩子：asr.* 变更 → 清单例。"""
    global _provider
    if any(k.startswith("asr.") for k in changed_keys):
        _provider = None


def is_stream_asr() -> bool:
    """是否流式 ASR（读类的 interface_type 属性，不实例化）。"""
    asr_type = _read_asr_config()["type"]
    if asr_type not in _REGISTRY:
        return False
    module_path, class_name = _REGISTRY[asr_type]
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return getattr(cls, "interface_type", "offline") == "stream"

"""OCR 工厂：按 ocr.type 创建 provider（可插拔 + 单例）。

B 类配置走 ConfigStore（同步从 _cache 取，warm 已预热）。
lifespan 在启动期调 subscribe(invalidate)，收到 ocr.* 变更时
清 _provider 单例，下次 get_ocr() 重新构造。
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from typing import Optional

from app.adapters.ocr.base import OCRProvider
from app.core.config_store import DEFAULTS, get_config_store

logger = logging.getLogger(__name__)

# ocr_type → (模块, 类名)
_REGISTRY = {
    "openai": ("app.adapters.ocr.openai_compatible", "OpenAICompatibleOCRProvider"),
    "baidu": ("app.adapters.ocr.baidu", "BaiduOCRProvider"),
}

_provider: Optional[OCRProvider] = None

_close_tasks: set[asyncio.Task] = set()


def _read_ocr_config() -> dict[str, object]:
    """从 ConfigStore 同步读 OCR 配置（warm 已预热）。"""
    store = get_config_store()

    def _g(key: str, cast=str, default=""):
        raw = store.get_sync(key, DEFAULTS.get(key, default))
        return cast(raw) if raw not in (None, "") else cast(default)
    return {
        "type": _g("ocr.type", str, "baidu"),
        "base_url": _g("ocr.base_url", str, ""),
        "api_key": _g("ocr.api_key", str, ""),
        "secret_key": _g("ocr.secret_key", str, ""),
        "model": _g("ocr.model", str, "general_basic"),
    }


def create_ocr() -> OCRProvider:
    """从 ConfigStore 同步读 OCR 配置 + 构造 provider。"""
    cfg = _read_ocr_config()
    if cfg["type"] not in _REGISTRY:
        raise ValueError(f"未知 OCR_TYPE={cfg['type']}，可选: {list(_REGISTRY)}")
    module_path, class_name = _REGISTRY[cfg["type"]]
    module = importlib.import_module(module_path)
    kwargs = {
        "base_url": cfg["base_url"],
        "api_key": cfg["api_key"],
        "model": cfg["model"],
    }
    if cfg["type"] == "baidu":
        kwargs["secret_key"] = cfg["secret_key"]
    return getattr(module, class_name)(**kwargs)


def get_ocr() -> OCRProvider:
    """单例（懒加载；整个进程只构造一次）。"""
    global _provider
    if _provider is None:
        _provider = create_ocr()
    return _provider


def _close_provider(p):
    if p is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    t = loop.create_task(p.aclose())
    _close_tasks.add(t)
    t.add_done_callback(_close_tasks.discard)


def invalidate(changed_keys: set[str]) -> None:
    """ConfigStore 订阅钩子：ocr.* 变更 → 关旧 provider 并清单例。"""
    global _provider
    if any(k.startswith("ocr.") for k in changed_keys):
        _close_provider(_provider)
        _provider = None


async def shutdown() -> None:
    """lifespan shutdown 调用：关闭当前 provider 的连接池（best-effort）。"""
    global _provider
    if _provider is not None:
        try:
            await _provider.aclose()
        except Exception as e:  # noqa: BLE001
            logger.warning("关闭 OCR provider 失败：%s", e)
        _provider = None

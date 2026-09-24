"""OCR 工厂：按 ocr.* / handwriting.* 两个独立 group 分别构造 provider。

通用 OCR 与手写 OCR 功能上无互通性，配置完全分离：
- 两个 group 各持一份 base_url/api_key/secret_key/model/language/type 配置
  （secret_key 仅 Baidu 实现使用）
- 各自按 group.type 实例化一个对应实现（OpenAI 兼容 / Baidu），单例独立缓存，
  不会跨 group 复用

B 类配置走 ConfigStore（同步从 _cache 取，warm 已预热）。
lifespan 在启动期调 subscribe(invalidate)，收到对应 group 变更时清该 group
的单例，下次 get_*() 重新构造。
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

# 通用 OCR 单例
_general_provider: Optional[OCRProvider] = None
# 手写 OCR 单例（独立 group，独立 access_token 缓存）
_handwriting_provider: Optional[OCRProvider] = None

_close_tasks: set[asyncio.Task] = set()


def _g(store, k: str, default: str = "") -> str:
    raw = store.get_sync(k, DEFAULTS.get(k, default))
    return raw if raw not in (None, "") else default


def _read_general_ocr_config() -> dict[str, object]:
    """读通用 OCR group(ocr.* 6 个 key)。"""
    store = get_config_store()
    return {
        "type": _g(store, "ocr.type", "baidu"),
        "base_url": _g(store, "ocr.base_url", ""),
        "api_key": _g(store, "ocr.api_key", ""),
        "secret_key": _g(store, "ocr.secret_key", ""),
        "model": _g(store, "ocr.model", "general_basic"),
        "language": _g(store, "ocr.language", "CHN_ENG"),
    }


def _read_handwriting_ocr_config() -> dict[str, object]:
    """读手写 OCR group(handwriting.* 6 个 key,完全独立)。"""
    store = get_config_store()
    return {
        "type": _g(store, "handwriting.type", "baidu"),
        "base_url": _g(store, "handwriting.base_url", ""),
        "api_key": _g(store, "handwriting.api_key", ""),
        "secret_key": _g(store, "handwriting.secret_key", ""),
        "model": _g(store, "handwriting.model", "handwriting"),
        "language": _g(store, "handwriting.language", "auto_detect"),
    }


def _build_provider(cfg: dict[str, object]) -> OCRProvider:
    """根据 cfg 构建单用途 provider 实例(每个 group 一个)。

    按 type 分发 kwargs:OpenAI 兼容类无 language/secret_key 形参,
    Baidu 全要——共用 kwargs 会让 OpenAI 类报 TypeError。
    """
    if cfg["type"] not in _REGISTRY:
        raise ValueError(f"未知 OCR_TYPE={cfg['type']}，可选: {list(_REGISTRY)}")
    module_path, class_name = _REGISTRY[cfg["type"]]
    module = importlib.import_module(module_path)
    if cfg["type"] == "openai":
        kwargs = {
            "base_url": cfg["base_url"],
            "api_key": cfg["api_key"],
            "model": cfg["model"],
        }
    else:  # baidu
        kwargs = {
            "base_url": cfg["base_url"],
            "api_key": cfg["api_key"],
            "model": cfg["model"],
            "secret_key": cfg["secret_key"],
            "language": cfg["language"],
        }
    return getattr(module, class_name)(**kwargs)


def create_general_ocr() -> OCRProvider:
    """从 ConfigStore 同步读通用 OCR 配置 + 构造 provider。"""
    cfg = _read_general_ocr_config()
    return _build_provider(cfg)


def create_handwriting_ocr() -> OCRProvider:
    """从 ConfigStore 同步读手写 OCR 配置 + 构造 provider。"""
    cfg = _read_handwriting_ocr_config()
    return _build_provider(cfg)


def get_general_ocr() -> OCRProvider:
    """通用 OCR provider 单例(持有自己的 access_token 缓存)。"""
    global _general_provider
    if _general_provider is None:
        _general_provider = create_general_ocr()
    return _general_provider


def get_handwriting_ocr() -> OCRProvider:
    """手写 OCR provider 单例(独立 access_token 缓存,与通用 OCR 完全独立)。"""
    global _handwriting_provider
    if _handwriting_provider is None:
        _handwriting_provider = create_handwriting_ocr()
    return _handwriting_provider


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
    """ConfigStore 订阅钩子：ocr.* / handwriting.* 变更 → 清对应单例。

    两组配置完全独立，单例也独立清，避免一方改动拖垮另一方已持有的 token。
    """
    global _general_provider, _handwriting_provider
    if any(k.startswith("ocr.") for k in changed_keys):
        _close_provider(_general_provider)
        _general_provider = None
    if any(k.startswith("handwriting.") for k in changed_keys):
        _close_provider(_handwriting_provider)
        _handwriting_provider = None


async def shutdown() -> None:
    """lifespan shutdown 调用：关闭两个 provider 的连接池(best-effort)。"""
    global _general_provider, _handwriting_provider
    for p in (_general_provider, _handwriting_provider):
        if p is not None:
            try:
                await p.aclose()
            except Exception as e:  # noqa: BLE001
                logger.warning("关闭 OCR provider 失败：%s", e)
    _general_provider = None
    _handwriting_provider = None

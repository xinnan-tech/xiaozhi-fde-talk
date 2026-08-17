"""LLM 工厂：按 llm_type 创建 provider（可插拔 + 单例）。

目前仅 openai（OpenAI 兼容）；非兼容流派（ollama 原生 / dify / gemini / coze）
后续加 adapters/llm/<name>.py + 注册到 _REGISTRY 即可。

B 类配置走 ConfigStore（同步从 _cache 取，warm 已预热）。
lifespan 在启动期调 subscribe(invalidate)，收到 llm.* 或 coach.llm_timeout_s 变更时
清 _provider 单例，下次 get_llm() 重新构造。
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from typing import Optional

from app.adapters.llm.base import LLMProvider
from app.core.config_store import DEFAULTS, get_config_store

logger = logging.getLogger(__name__)

# llm_type → (模块, 类名)
_REGISTRY = {
    "openai": ("app.adapters.llm.openai_compatible", "OpenAILLMProvider"),
}

_provider: Optional[LLMProvider] = None

_close_tasks: set[asyncio.Task] = set()


def _read_llm_config() -> dict[str, object]:
    """从 ConfigStore 同步读 LLM + coach.llm_timeout_s（warm 已预热）。"""
    store = get_config_store()

    def _g(key: str, cast=str, default=""):
        raw = store.get_sync(key, DEFAULTS.get(key, default))
        return cast(raw) if raw not in (None, "") else cast(default)
    return {
        "type": _g("llm.type", str, "openai"),
        "base_url": _g("llm.base_url", str, ""),
        "api_key": _g("llm.api_key", str, ""),
        "model": _g("llm.model", str, "qwen-plus"),
        "llm_timeout_s": _g("coach.llm_timeout_s", float, "45.0"),
    }


def create_llm() -> LLMProvider:
    """从 ConfigStore 同步读 LLM 配置 + 构造 provider。"""
    cfg = _read_llm_config()
    if cfg["type"] not in _REGISTRY:
        raise ValueError(f"未知 LLM_TYPE={cfg['type']}，可选: {list(_REGISTRY)}")
    module_path, class_name = _REGISTRY[cfg["type"]]
    module = importlib.import_module(module_path)
    return getattr(module, class_name)(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        llm_timeout_s=float(cfg["llm_timeout_s"]),
    )


def get_llm() -> LLMProvider:
    """单例（懒加载；整个进程只构造一次）。"""
    global _provider
    if _provider is None:
        _provider = create_llm()
    return _provider


def _close_provider(p):
    if p is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 无运行中的事件循环（进程退出期等），无可调度对象
    t = loop.create_task(p.aclose())
    _close_tasks.add(t)
    t.add_done_callback(_close_tasks.discard)


def invalidate(changed_keys: set[str]) -> None:
    """ConfigStore 订阅钩子：llm.* 或 coach.llm_timeout_s 变更 → 关旧 provider 并清单例。"""
    global _provider
    if any(k.startswith("llm.") or k.startswith("coach.llm_timeout_s") for k in changed_keys):
        _close_provider(_provider)
        _provider = None


async def shutdown() -> None:
    """lifespan shutdown 调用：关闭当前 provider 的连接池（best-effort）。"""
    global _provider
    if _provider is not None:
        try:
            await _provider.aclose()
        except Exception as e:  # noqa: BLE001
            logger.warning("关闭 LLM provider 失败：%s", e)
        _provider = None
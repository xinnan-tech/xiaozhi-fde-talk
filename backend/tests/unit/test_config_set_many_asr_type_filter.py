"""set_many 过滤非激活 ASR 类型的字段（#177）。

复现：admin 选了 funasr_server，前端 payload 仍带空 doubao_stream.api_key
（REQUIRED_STRING_KEYS 一员）。旧实现会被 validate_value 拒 400，导致用户无法
保存已配好的 ws_url。

修复后行为：
- asr.type 在 items 里 → 以 items 为准，丢弃其他 asr.<other>.* 字段
- asr.type 不在 items 但 cache 里有 → 用 cache 的类型
- 不带 asr.type（首启动 / 单元测试）/ cache 为空 → 不过滤
- 非 asr.* 字段永远不参与丢弃
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config_store import ConfigStore


@pytest.fixture
def store():
    prev_instance = ConfigStore._instance
    ConfigStore._instance = None
    s = ConfigStore()
    s._cache = {
        "asr.type": "funasr_server",
        "asr.funasr_server.ws_url": "wss://legacy:10096",
        "asr.funasr_server.language": "zh",
        "asr.doubao_stream.api_key": "old-doubao-key",
    }
    ConfigStore._instance = s
    yield s
    ConfigStore._instance = prev_instance


def _patch_session(monkeypatch, captured: dict):
    """mock SessionLocal 使 set_many 走 fake session，避免 DB 依赖。

    `captured` 留作扩展位（execute 入参是 SQLAlchemy stmt，目前不解析），
    测试通过断言 store._cache 副作用来验证过滤行为。
    """
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.commit = AsyncMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    session.execute = AsyncMock(side_effect=captured.setdefault("execute", AsyncMock()))
    monkeypatch.setattr("app.core.config_store.SessionLocal", lambda: session)
    return session


@pytest.mark.asyncio
async def test_set_many_drops_inactive_asr_type_required_fields(store, monkeypatch):
    """#177 复现：admin 选 funasr_server，payload 含空 doubao_stream.api_key。
    set_many 必须丢弃非激活类型的空必填项，不能让它触发 REQUIRED_STRING_KEYS 校验。
    """
    captured: dict = {}
    _patch_session(monkeypatch, captured)

    await store.set_many({
        "asr.type": "funasr_server",
        "asr.funasr_server.ws_url": "wss://192.168.4.36:10096",
        "asr.funasr_server.language": "zh",
        "asr.funasr_server.sample_rate": "16000",
        "asr.doubao_stream.api_key": "",  # 非激活类型空必填 → 必须丢弃
        "asr.doubao_stream.language": "zh-CN",
        "asr.doubao_stream.sample_rate": "16000",
    })

    # execute 入参是 SQLAlchemy stmt，无法直接读 (key, value)；改通过
    # 缓存 + 通知断言副作用。
    assert store._cache["asr.funasr_server.ws_url"] == "wss://192.168.4.36:10096"
    # 非激活类型的旧值不应被空串覆盖——它根本不该进入 upsert 流程
    assert store._cache["asr.doubao_stream.api_key"] == "old-doubao-key"


@pytest.mark.asyncio
async def test_set_many_keeps_inactive_keys_when_switching_type(store, monkeypatch):
    """切换 asr.type 到 doubao_stream 时，items 里带 funasr_server 的字段也应被丢
    ——admin 明确切了类型，旧的 funasr_server 配置不再有效（虽然 cache 还会保留）。
    """
    captured: dict = {}
    _patch_session(monkeypatch, captured)

    await store.set_many({
        "asr.type": "doubao_stream",
        "asr.doubao_stream.api_key": "new-api-key",
        # 前端切类型时把旧类型字段也发过来了（典型 bug）
        "asr.funasr_server.ws_url": "",
        "asr.funasr_server.language": "zh",
    })

    # 新类型被写入
    assert store._cache["asr.doubao_stream.api_key"] == "new-api-key"
    # 旧类型字段不应被空串刷掉——它们只是没参与本次 upsert，cache 保留旧值
    assert store._cache["asr.funasr_server.ws_url"] == "wss://legacy:10096"


@pytest.mark.asyncio
async def test_set_many_without_asr_type_keeps_everything(store, monkeypatch):
    """首启动 / 其他 admin 端不更新 asr.type 时，不过滤 asr.* 字段——保持旧契约。
    """
    captured: dict = {}
    _patch_session(monkeypatch, captured)

    await store.set_many({
        # 没有 asr.type 字段，纯粹刷一个非 ASR 配置
        "coach.pause_s": "5.0",
        "asr.funasr_server.ws_url": "wss://other:10096",
    })

    assert store._cache["coach.pause_s"] == "5.0"
    assert store._cache["asr.funasr_server.ws_url"] == "wss://other:10096"


@pytest.mark.asyncio
async def test_set_many_uses_cache_asr_type_when_items_lack_it(store, monkeypatch):
    """items 不含 asr.type 但 cache 有 → 用 cache 的激活类型过滤。覆盖 e2e 场景下
    admin 分两步提交（先切类型保存其他字段）的边界情况。
    """
    captured: dict = {}
    _patch_session(monkeypatch, captured)

    await store.set_many({
        # 没有 asr.type
        "asr.funasr_server.language": "en",  # 激活类型
        "asr.doubao_stream.api_key": "",  # 非激活类型 → 应被丢
    })

    assert store._cache["asr.funasr_server.language"] == "en"
    # 非激活类型空值不应写入
    assert store._cache["asr.doubao_stream.api_key"] == "old-doubao-key"

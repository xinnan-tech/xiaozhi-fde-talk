"""Settings prod 校验器回归：DB_URL + ASR_WS_URL prod 拒绝路径。

与 Wave 1 的 prod_no_sqlite 校验同理——新增 ASR_WS_URL 校验覆盖同样套路：
prod 模式下来自本机/loopback 的 ASR 地址拒启动，dev/test 允许（开发者本地 FunASR）。
"""
from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys


def _make_settings(**overrides):
    """绕开 lru_cache 单例：临时把不相关 env 清掉后构造 Settings。"""
    import app.core.settings as sm
    from app.core.settings import Settings
    sm.get_settings.cache_clear()
    base = {"env": "prod", "asr_ws_url": "ws://funasr:10095"}
    base.update(overrides)
    return Settings(**base)


def test_prod_rejects_localhost_asr_ws_url():
    """prod 模式 + ASR_WS_URL 指向 localhost → 必须抛 I18nError(SETTINGS_PROD_ASR_LOCALHOST)。"""
    with pytest.raises(I18nError) as ei:
        _make_settings(
            db_url="postgresql+asyncpg://u:p@db:5432/x",
            asr_ws_url="wss://localhost:10096",
        )
    assert ei.value.code == Keys.SETTINGS_PROD_ASR_LOCALHOST.value


def test_prod_rejects_127_asr_ws_url():
    """127.0.0.1 也是 loopback → prod 拒。"""
    with pytest.raises(I18nError) as ei:
        _make_settings(
            db_url="postgresql+asyncpg://u:p@db:5432/x",
            asr_ws_url="ws://127.0.0.1:10095",
        )
    assert ei.value.code == Keys.SETTINGS_PROD_ASR_LOCALHOST.value


def test_prod_rejects_zero_ip_asr_ws_url():
    """0.0.0.0 在容器内指向容器自身 → prod 拒。"""
    with pytest.raises(I18nError) as ei:
        _make_settings(
            db_url="postgresql+asyncpg://u:p@db:5432/x",
            asr_ws_url="ws://0.0.0.0:10095",
        )
    assert ei.value.code == Keys.SETTINGS_PROD_ASR_LOCALHOST.value


def test_prod_accepts_real_host_asr_ws_url():
    """prod + 真实 host → 通过。"""
    s = _make_settings(
        db_url="postgresql+asyncpg://u:p@db:5432/x",
        asr_ws_url="ws://funasr.internal:10095",
    )
    assert s.asr_ws_url == "ws://funasr.internal:10095"


def test_dev_allows_localhost_asr_ws_url():
    """dev 不限制 localhost：开发者本地 FunASR 默认开箱即用。"""
    s = _make_settings(env="dev", asr_ws_url="wss://localhost:10096")
    assert s.asr_ws_url == "wss://localhost:10096"


def test_test_allows_localhost_asr_ws_url():
    """test 模式同样放行 localhost。"""
    s = _make_settings(env="test", asr_ws_url="ws://127.0.0.1:10095")
    assert s.asr_ws_url == "ws://127.0.0.1:10095"

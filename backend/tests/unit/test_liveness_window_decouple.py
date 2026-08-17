"""P2-1 · liveness_window_s 与 grace_period_s 解耦后的配置对称性。

M6 原意：grace（manager 翻 SUSPENDED）与 liveness（registry 销毁 runtime）是两套
独立存活窗口（P1-3/P1-4 已拆分定时器、明确归属）。但 grace_period_s 走 config_store
运行时可调，liveness_window_s 却 frozen 在 SessionPolicy=60s —— 运营无法调，不对称。

本任务收窄为：让 liveness_window_s 也走 config_store（与 grace 对称）。
明确不做：park 传 on_expire=SUSPENDED —— 两窗口模型下 SUSPENDED 翻转归 manager 的
grace 定时器，liveness 到期再翻会触发 SUSPENDED→SUSPENDED 非法转换，有害无益。

判定：get_session_runtime_config() 应返回 liveness_window_s（取自 config_store）。
当前只返回 grace/idle，缺 liveness → 红；补 key 后 → 绿。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core import config_store as cs_module
from app.core.config_store import get_session_runtime_config


@pytest.mark.asyncio
async def test_runtime_config_exposes_liveness_window(monkeypatch):
    """get_session_runtime_config 应包含从 config_store 读到的 liveness_window_s。"""
    async def _fake_get(key):  # noqa: ANN001
        return {
            "session.grace_period_s": "60.0",
            "session.idle_timeout_s": "120.0",
            "session.idle_check_interval_s": "30.0",
            "session.liveness_window_s": "77.0",  # 非默认 60，证明来自 config
        }.get(key)

    fake_store = MagicMock()
    fake_store.get = _fake_get
    monkeypatch.setattr(cs_module, "get_config_store", lambda: fake_store)

    cfg = await get_session_runtime_config()

    assert "liveness_window_s" in cfg, "get_session_runtime_config 缺 liveness_window_s"
    assert cfg["liveness_window_s"] == 77.0


def test_liveness_window_key_is_tunable():
    """liveness_window_s 应进入 config_store 白名单（运营可调，与 grace 对称）。"""
    assert "session.liveness_window_s" in cs_module.ALL_B_KEYS
    assert "session.liveness_window_s" in cs_module.DEFAULTS

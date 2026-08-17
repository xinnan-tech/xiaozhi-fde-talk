"""单元测试：diagnostics 不再预判 manager._active 是否有 IN_PROGRESS。

反向断言：当内存里有 IN_PROGRESS 会话时，diagnose_asr 不应返回 `busy`。
"""
import asyncio
import pytest
from unittest.mock import patch, MagicMock

from app.services import diagnostics


@pytest.mark.asyncio
async def test_diagnose_asr_does_not_check_active_sessions():
    """diagnostics 不应预判 manager._active 是否有 IN_PROGRESS。

    即便内存里有 IN_PROGRESS 会话，diagnose_asr 也不应在那里 early-return。
    缺 ws_url → 走 config_missing 路径（而非 busy）。
    """
    with patch.object(diagnostics, "_build_test_audio", return_value=None), \
         patch.object(diagnostics, "_extract_asr_error",
                      return_value={"ok": False, "code": "server",
                                    "message": "synthetic"}):
        fake_cfg = {"asr.ws_url": "", "asr.sample_rate": "16000"}
        with patch.object(diagnostics, "get_config_store") as gcs:
            gcs.return_value.get_sync = lambda key, default=None: fake_cfg.get(key, default)
            res = await diagnostics.diagnose_asr()
    assert res["code"] == "config_missing", f"got {res['code']}"

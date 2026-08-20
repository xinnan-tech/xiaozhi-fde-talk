"""端点 /extract 接通 extract_prompts.build_extract_system + llm.output_language。

Task 2 的端到端闭环：用户偏好语种（store 里的 llm.output_language）→ directive 注入。

Auth 模式：参考 tests/unit/test_diagnostics_admin.py:27-40 的 dependency_overrides 模式
—— override `get_current_user` 返 fake `CurrentUser`，不走 Bearer token。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.i18n.extract_prompts import build_extract_system
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user


@pytest.fixture
def extract_client():
    """TestClient + get_current_user override + LLM mock：仅断言 system prompt 注入。"""
    from app.app import create_app

    app = create_app()

    async def _fake_user() -> CurrentUser:
        return CurrentUser(user_id="extract-test-user", username="user", role="user")

    app.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app)


def _post_extract(client, transcript: str = "客户是 ABC 公司 CEO 张三", fields: list[str] | None = None):
    return client.post(
        "/api/v1/interviews/extract",
        json={
            "transcript": transcript,
            "template_id": "test-template",
            "fields": fields or ["name", "company"],
            "field_labels": {"name": "姓名", "company": "公司"},
            "field_types": {"name": "text", "company": "text"},
            "current_values": {},
        },
    )


def test_extract_zh_cn_directive_in_system_prompt(extract_client):
    """未配置 llm.output_language → 默认 zh_cn → 指令含「简体中文」。"""
    captured = {}

    async def fake_chat_json(system, user):
        captured["system"] = system
        return {"name": "张三", "company": "ABC"}

    async def fake_store_get(key):
        # store 未配置 → 返 None，端点 fallback 到 "zh_cn"
        return None

    from unittest.mock import MagicMock

    fake_store = MagicMock()
    fake_store.get = fake_store_get

    with patch("app.adapters.llm.factory.get_llm") as mock_get_llm, \
         patch("app.transport.http.routes.interviews.get_config_store", return_value=fake_store):
        mock_get_llm.return_value.chat_json = fake_chat_json
        r = _post_extract(extract_client)

    assert r.status_code == 200, r.text
    assert "简体中文" in captured["system"], f"system prompt 缺 directive: {captured['system'][:300]}"
    assert "ABC" in captured["system"]


def test_extract_en_directive_in_system_prompt(extract_client):
    """store['llm.output_language']='en' → 指令含 'English' 且不含「简体中文」。"""
    captured = {}

    async def fake_chat_json(system, user):
        captured["system"] = system
        return {"name": "Zhang San", "company": "ABC"}

    async def fake_store_get(key):
        return "en" if key == "llm.output_language" else None

    from unittest.mock import MagicMock

    fake_store = MagicMock()
    fake_store.get = fake_store_get

    with patch("app.adapters.llm.factory.get_llm") as mock_get_llm, \
         patch("app.transport.http.routes.interviews.get_config_store", return_value=fake_store):
        mock_get_llm.return_value.chat_json = fake_chat_json
        r = _post_extract(extract_client)

    assert r.status_code == 200, r.text
    assert "English" in captured["system"]
    assert "简体中文" not in captured["system"]


def test_extract_directive_keys_match_lang_meta():
    """build_extract_system 仍接受 _LANG_META 所有语种（接口层保证）。"""
    out_en = build_extract_system("en", today="2026-08-20", current_values="", transcript="", fields=[])
    out_zh = build_extract_system("zh_cn", today="2026-08-20", current_values="", transcript="", fields=[])
    assert "English" in out_en
    assert "简体中文" in out_zh

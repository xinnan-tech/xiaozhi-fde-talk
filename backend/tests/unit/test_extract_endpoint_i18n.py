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


async def test_extract_real_config_store_uses_llm_output_language_key(extract_client):
    """真 config store（不 mock）：init_db+warm → snapshot → set 'en' → 端点读 'en' → 指令含 'English' → restore。

    验 key 名拼写：若代码改成 llm.output_lang，set 注入失效，endpoint 仍 fallback zh_cn，本测试 fail。
    走 public API（get/set）而非私有 _cache，DB + cache + broadcast 都生效；finally 按 snapshot 还原。

    不走 `with TestClient(app)` 触发 lifespan——manager.start_idle_watchdog() 创建的
    asyncio.Event 绑死在 TestClient 内部 loop，pytest-asyncio 的 async 测试另起 loop
    会 RuntimeError。这里只调 init_db + warm 拿 DEFAULTS 种入（含 llm.output_language
    ="zh_cn"），跳过 JWT 解析 / 僵尸清扫 / 模板加载 / watchdog 这些与本测试无关的副作用。
    下面的 assert 把「DB 一定有 llm.output_language 行」从注释里的隐含前提变成代码里的校验。
    """
    from app.core.config_store import get_config_store
    from app.persistence.bootstrap import init_db

    store = get_config_store()
    key = "llm.output_language"

    # 手动跑 init_db + warm：建表 + 种 DEFAULTS（lifespan 那条路 watchdog 会绑 loop）
    await init_db()
    await store.warm()

    original = await store.get(key)
    assert original is not None, (
        f"warm() 跑完 DB 应有 {key!r} 默认行（DEFAULTS['llm.output_language']='zh_cn'），"
        f"实际为 None——查 init_db 是否建表成功、warm 是否读到 DEFAULTS。"
    )

    captured = {}

    async def fake_chat_json(system, user):
        captured["system"] = system
        return {"name": "Zhang San", "company": "ABC"}

    try:
        await store.set(key, "en")

        with patch("app.adapters.llm.factory.get_llm") as mock_get_llm:
            mock_get_llm.return_value.chat_json = fake_chat_json
            r = _post_extract(extract_client)

        assert r.status_code == 200, r.text
        assert "English" in captured["system"], f"system prompt 缺 'English' directive: {captured['system'][:300]}"
        assert "简体中文" not in captured["system"]
    finally:
        await store.set(key, original)

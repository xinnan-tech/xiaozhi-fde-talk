"""e2e：用户上传名片图片 → /ocr 识别文字 → /extract 按用户偏好语种生成字段值。

本测试不调真 OCR/LLM——mock adapter 与 mock chat_json，断言链路正确接通：
- /ocr 用 OCR_PROMPT（Task 3 英文 base）
- /extract system_prompt 含用户偏好语种的 directive（Task 2 注入）
"""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.i18n.ocr_prompts import OCR_PROMPT
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user


@pytest.fixture
def e2e_client():
    from app.app import create_app

    app = create_app()

    async def _fake_user() -> CurrentUser:
        return CurrentUser(user_id="e2e-user", username="user", role="user")

    app.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app)


def _post_extract(client, transcript: str, fields: list[str] | None = None,
                  field_labels: dict | None = None, field_types: dict | None = None):
    return client.post(
        "/api/v1/interviews/extract",
        json={
            "transcript": transcript,
            "template_id": "test-template",
            "fields": fields or ["name", "company"],
            "field_labels": field_labels or {"name": "姓名", "company": "公司"},
            "field_types": field_types or {"name": "text", "company": "text"},
            "current_values": {},
        },
    )


def test_ocr_to_extract_pipeline_zh_cn(e2e_client):
    """中文偏好下：/ocr 返 OCR_PROMPT 提取的文字 → /extract 按 zh_cn directive 处理。"""
    captured = {}

    async def fake_recognize(image_bytes, **_):
        return "客户是 ABC 公司 CEO 张三"

    async def fake_chat_json(system, user):
        captured["system"] = system
        return {"name": "张三", "company": "ABC 公司"}

    fake_store = MagicMock()
    async def fake_store_get(key):
        return None
    fake_store.get = fake_store_get

    fake_image = b"\x89PNG_FAKE"
    b64 = base64.b64encode(fake_image).decode()

    with patch("app.adapters.ocr.factory.get_ocr") as mock_get_ocr, \
         patch("app.adapters.llm.factory.get_llm") as mock_get_llm, \
         patch("app.transport.http.routes.interviews.get_config_store", return_value=fake_store):
        mock_get_ocr.return_value.configured = True
        mock_get_ocr.return_value.recognize = fake_recognize
        mock_get_llm.return_value.chat_json = fake_chat_json

        r1 = e2e_client.post("/api/v1/interviews/ocr", json={"image_base64": b64})
        assert r1.status_code == 200, r1.text
        ocr_text = r1.json()["text"]
        assert ocr_text == "客户是 ABC 公司 CEO 张三"

        r2 = _post_extract(e2e_client, ocr_text)
        assert r2.status_code == 200, r2.text
        values = r2.json()["values"]
        assert values["name"] == "张三"
        assert values["company"] == "ABC 公司"
        assert "简体中文" in captured["system"]


def test_ocr_to_extract_pipeline_en(e2e_client):
    """英文偏好下：/extract system_prompt 含 'English' directive。"""
    captured = {}

    async def fake_recognize(image_bytes, **_):
        return "CEO Zhang San of ABC Corp"

    async def fake_chat_json(system, user):
        captured["system"] = system
        return {"name": "Zhang San", "company": "ABC Corp"}

    fake_store = MagicMock()
    async def fake_store_get(key):
        return "en" if key == "llm.output_language" else None
    fake_store.get = fake_store_get

    fake_image = b"\x89PNG_FAKE"
    b64 = base64.b64encode(fake_image).decode()

    with patch("app.adapters.ocr.factory.get_ocr") as mock_get_ocr, \
         patch("app.adapters.llm.factory.get_llm") as mock_get_llm, \
         patch("app.transport.http.routes.interviews.get_config_store", return_value=fake_store):
        mock_get_ocr.return_value.configured = True
        mock_get_ocr.return_value.recognize = fake_recognize
        mock_get_llm.return_value.chat_json = fake_chat_json

        r1 = e2e_client.post("/api/v1/interviews/ocr", json={"image_base64": b64})
        assert r1.status_code == 200, r1.text

        r2 = _post_extract(
            e2e_client, r1.json()["text"],
            field_labels={"name": "Name", "company": "Company"},
        )
        assert r2.status_code == 200, r2.text
        assert "简体中文" not in captured["system"]
        assert "English" in captured["system"]


def test_ocr_prompt_constant_used_by_endpoint(e2e_client):
    """/ocr 路由调 OCR adapter 时应使用 OCR_PROMPT 常量。"""
    captured_prompts = []

    async def fake_recognize(image_bytes, prompt=None, **kwargs):
        captured_prompts.append(prompt)
        return ""

    fake_image = b"\x89PNG_FAKE"
    b64 = base64.b64encode(fake_image).decode()

    with patch("app.adapters.ocr.factory.get_ocr") as mock_get_ocr:
        mock_get_ocr.return_value.configured = True
        mock_get_ocr.return_value.recognize = fake_recognize
        e2e_client.post("/api/v1/interviews/ocr", json={"image_base64": b64})

    assert len(captured_prompts) == 1
    assert captured_prompts[0] == OCR_PROMPT

"""/ocr 路由图片格式白名单 e2e 校验。

只接受 JPEG / PNG / BMP 三种 magic bytes；其它格式（GIF / WEBP /
TIFF / HEIC / AVIF / 纯文本 / 过短字节）必须被 422 + 错误码
`http.ocr.image_format_unsupported` 拒绝，避免垃圾字节送上游 OCR provider。
"""
from __future__ import annotations

import base64
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.i18n import t
from app.core.i18n.messages import Keys
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user


@pytest.fixture
def client():
    from app.app import create_app

    app = create_app()

    async def _fake_user() -> CurrentUser:
        return CurrentUser(user_id="u", username="u", role="user")

    app.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app)


def _post_ocr(client, payload: bytes) -> "tuple[int, dict]":
    b64 = base64.b64encode(payload).decode()
    with patch("app.adapters.ocr.factory.get_ocr") as mock_get_ocr:
        mock_get_ocr.return_value.configured = True
        mock_get_ocr.return_value.recognize = _ok_recognize
        r = client.post("/api/v1/interviews/ocr", json={"image_base64": b64})
    return r.status_code, r.json()


async def _ok_recognize(image_bytes, **_):
    return "ok"


@pytest.mark.parametrize(
    "name,header",
    [
        ("jpeg", b"\xff\xd8\xff\xe0\x00\x10JFIF"),
        ("png", b"\x89PNG\r\n\x1a\n"),
        ("bmp", b"BM" + b"\x00" * 14),
    ],
)
def test_allowed_image_formats_pass(client, name, header):
    """JPEG / PNG / BMP 三种白名单格式必须放行。"""
    status, body = _post_ocr(client, header + b"\x00" * 16)
    assert status == 200, body
    assert body["text"] == "ok"


@pytest.mark.parametrize(
    "name,header",
    [
        # GIF87a / GIF89a
        ("gif", b"GIF89a" + b"\x00" * 8),
        # RIFF .... WEBP
        ("webp", b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8),
        # TIFF little-endian / big-endian
        ("tiff_le", b"II*\x00" + b"\x00" * 8),
        ("tiff_be", b"MM\x00*" + b"\x00" * 8),
        # HEIC / HEIF / AVIF (ISO base media file format，bytes 4-7 是 ftyp)
        ("heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 8),
        ("avif", b"\x00\x00\x00\x18ftypavif" + b"\x00" * 8),
        # SVG (XML 头)
        ("svg", b"<?xml version=\"1.0\"?><svg xmlns=\"http://www.w3.org/2000/svg\"/>"),
        # ICO
        ("ico", b"\x00\x00\x01\x00" + b"\x00" * 8),
        # 纯文本
        ("plain_text", b"hello world this is plain text"),
    ],
)
def test_unsupported_image_formats_rejected(client, name, header):
    """非白名单格式必须 422 + 错误码 image_format_unsupported。"""
    status, body = _post_ocr(client, header)
    assert status == 422, f"{name}: expected 422, got {status} {body}"
    assert body["code"] == Keys.HTTP_OCR_IMAGE_FORMAT_UNSUPPORTED.value
    # zh-CN locale 翻译含「图片格式」语义
    rendered = t(Keys.HTTP_OCR_IMAGE_FORMAT_UNSUPPORTED.value, locale="zh-CN")
    assert "格式" in rendered or "jpg" in rendered.lower()


def test_empty_bytes_rejected(client):
    """空 base64 解码后是空字节，必须被拒。"""
    status, body = _post_ocr(client, b"")
    assert status == 422, body
    assert body["code"] == Keys.HTTP_OCR_IMAGE_FORMAT_UNSUPPORTED.value


def test_short_bytes_rejected(client):
    """2 字节 \xff\xd8 不能匹配任何 magic bytes 嗅探，必须被拒。"""
    status, body = _post_ocr(client, b"\xff\xd8")
    assert status == 422, body
    assert body["code"] == Keys.HTTP_OCR_IMAGE_FORMAT_UNSUPPORTED.value


def test_jpeg_with_low_byte_only_rejected(client):
    """\xff\xd8 单字节前缀不够，必须 \xff\xd8\xff 三个字节起头才认 JPEG。"""
    status, body = _post_ocr(client, b"\xff\xd8\x00\x00\x00\x00\x00\x00")
    assert status == 422, body
    assert body["code"] == Keys.HTTP_OCR_IMAGE_FORMAT_UNSUPPORTED.value


def test_bmp_signature_two_bytes(client):
    """BMP 仅需 'BM' 两字节即可识别（最短 BMP header）。"""
    status, body = _post_ocr(client, b"BM\x00\x00\x00\x00")
    assert status == 200, body

"""手写图 hash + 格式嗅探 + dedup 单元测试。

不依赖 DB / 网络,纯函数式校验:同一字节串 hash 一致、不同字节串 hash 不一致、
格式嗅探按 magic bytes 准确分类。
"""
from __future__ import annotations

import base64

import pytest

from app.services.handwriting.service import (
    compute_image_hash,
    compute_image_hash_from_bytes,
    sniff_image_format,
)


def _b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("ascii")


# ---- hash ----

def test_hash_same_image_same_digest():
    """同字节串 → 同 hash(去重命中条件)。"""
    img = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    assert compute_image_hash(_b64(img)) == compute_image_hash(_b64(img))


def test_hash_different_image_different_digest():
    """不同字节串 → 不同 hash。"""
    img_a = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    img_b = b"\x89PNG\r\n\x1a\n" + b"\x00" * 17
    assert compute_image_hash(_b64(img_a)) != compute_image_hash(_b64(img_b))


def test_hash_from_bytes_matches_str_entry():
    """compute_image_hash_from_bytes 与 str 版结果一致——避免双入口漂移。"""
    img = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 8
    assert compute_image_hash_from_bytes(img) == compute_image_hash(_b64(img))


def test_hash_is_sha256_hex_64chars():
    """hash 长度 = sha256 hex = 64。"""
    img = b"\x00" * 4
    h = compute_image_hash(_b64(img))
    assert len(h) == 64
    int(h, 16)  # 必须是合法 hex


# ---- 格式嗅探 ----

@pytest.mark.parametrize(
    "header,expected",
    [
        (b"\xff\xd8\xff\xe0", "jpeg"),
        (b"\xff\xd8\xff\xe1", "jpeg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"BM\x00\x00\x00\x00", "bmp"),
        (b"GIF89a", ""),  # 不在白名单
        (b"RIFF", ""),    # WEBP
        (b"\x00\x00\x00\x18ftyp", ""),  # MP4
        (b"", ""),
    ],
)
def test_sniff_image_format(header, expected):
    """magic bytes 嗅探:白名单(jpeg/png/bmp)返回对应格式,其它返空串。"""
    assert sniff_image_format(header) == expected


def test_sniff_format_real_jpeg():
    """真实 JPEG magic bytes 仍能被识别。"""
    # 极简 JPEG 文件:SOI(FFD8FF)+ APP0 marker + 16 字节 JFIF + EOI
    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
    assert sniff_image_format(jpeg) == "jpeg"
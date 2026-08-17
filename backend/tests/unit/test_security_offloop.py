from __future__ import annotations
import asyncio
from app.core import security


async def test_hash_and_verify_async_roundtrip():
    h = await security.hash_password_async("s3cret")
    assert await security.verify_password_async("s3cret", h) is True
    assert await security.verify_password_async("wrong", h) is False

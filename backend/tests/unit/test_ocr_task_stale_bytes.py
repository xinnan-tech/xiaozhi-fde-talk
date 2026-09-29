"""_ocr_with_retry 循环内重新 fetch + b64decode,保证重试用最新 bytes。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_image(image_id: int = 42, *, image_hash: str = "h1", image_base64: str = "QQ=="):
    """image_base64='QQ==' → decoded bytes b'A' (1 byte),image_bytes_size=1。"""
    from app.persistence.models import HandwritingImage
    return HandwritingImage(
        id=image_id,
        session_id="s1",
        user_id="u1",
        image_base64=image_base64,
        image_format="jpeg",
        image_bytes_size=1,
        ocr_status="pending",
        text="",
        retry_count=0,
        image_hash=image_hash,
        client_created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_ocr_task_skips_when_image_hash_changed(monkeypatch):
    """循环内 fetch 时如果 ocr_status 已被并发 task 标 done → 当前 task 退出。"""
    from app.services.handwriting import ocr_task as ocr_task_mod

    # 模拟"第 1 次 fetch 时 ocr_status 已变 done"
    img = _make_image()
    img.ocr_status = "done"  # 已被其他 task 完成
    img.text = "已存在的 OCR 文本"

    @asynccontextmanager
    async def _ctx():
        sess = MagicMock()

        async def get(cls, pk):
            return img

        sess.get = get
        sess.commit = AsyncMock()
        yield sess

    monkeypatch.setattr(ocr_task_mod, "SessionLocal", _ctx)
    # provider 不应该被调用——task 应该跳过
    provider_called = {"n": 0}

    async def fake_recognize(*args, **kwargs):
        provider_called["n"] += 1
        return "new_ocr_text"

    fake_provider = MagicMock()
    fake_provider.recognize = fake_recognize
    monkeypatch.setattr(ocr_task_mod, "get_handwriting_ocr", lambda: fake_provider)

    await ocr_task_mod._ocr_with_retry(image_id=42, session_id="s1")

    # provider 未被调(本 task 退出),text 保持原值
    assert provider_called["n"] == 0
    assert img.text == "已存在的 OCR 文本"


@pytest.mark.asyncio
async def test_ocr_task_re_reads_image_each_attempt(monkeypatch):
    """循环内每次重新 fetch + b64decode,保证 OCR 用最新 bytes。"""
    from app.services.handwriting import ocr_task as ocr_task_mod

    img = _make_image()
    fetch_count = {"n": 0}
    call_count = {"n": 0}

    @asynccontextmanager
    async def _ctx():
        sess = MagicMock()

        async def get(cls, pk):
            fetch_count["n"] += 1
            return img

        sess.get = get
        sess.commit = AsyncMock()
        yield sess

    monkeypatch.setattr(ocr_task_mod, "SessionLocal", _ctx)

    # 失败路径:provider.recognize 前 2 次失败,第 3 次成功
    fake_provider = MagicMock()

    async def recognize(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError(f"模拟失败 #{call_count['n']}")
        return "ocr_text"

    fake_provider.recognize = recognize
    monkeypatch.setattr(ocr_task_mod, "get_handwriting_ocr", lambda: fake_provider)

    # mock sleep 加速(避免等 30s × 4)
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        await real_sleep(0)

    monkeypatch.setattr(ocr_task_mod.asyncio, "sleep", fake_sleep)

    # mock runtime(避免调真 DB 写镜像列 datetime 序列化)
    monkeypatch.setattr("app.services.sessions.runtime.registry.get", lambda sid: None)

    await ocr_task_mod._ocr_with_retry(image_id=42, session_id="s1")

    # 失败 2 次 + 成功 1 次 = 3 轮 fetch(每轮都重新 SELECT img)
    assert fetch_count["n"] == 3
    # provider 调用 3 次(2 失败 + 1 成功)
    assert call_count["n"] == 3
    # 第 3 次成功 → text 写入
    assert img.text == "ocr_text"
    assert img.ocr_status == "done"


@pytest.mark.asyncio
async def test_ocr_task_marks_failed_on_decode_error(monkeypatch):
    """循环内 fetch 时 base64 decode 失败 → ocr_status=failed 退出。"""
    from app.services.handwriting import ocr_task as ocr_task_mod

    img = _make_image()
    img.image_base64 = "!!!"  # 无效 base64

    @asynccontextmanager
    async def _ctx():
        sess = MagicMock()

        async def get(cls, pk):
            return img

        sess.get = get
        sess.commit = AsyncMock()
        yield sess

    monkeypatch.setattr(ocr_task_mod, "SessionLocal", _ctx)
    fake_provider = MagicMock()
    fake_provider.recognize = AsyncMock()
    monkeypatch.setattr(ocr_task_mod, "get_handwriting_ocr", lambda: fake_provider)

    await ocr_task_mod._ocr_with_retry(image_id=42, session_id="s1")

    # decode 失败 → failed,recognize 没被调
    assert img.ocr_status == "failed"
    assert img.retry_count == 1
    assert fake_provider.recognize.await_count == 0


@pytest.mark.asyncio
async def test_ocr_task_exits_when_canvas_redrawn(monkeypatch):
    """画板重画:image_hash 变了 → 旧 task 退出,不再 OCR(老图)。

    模拟:第 1 轮 fetch image_hash=h1 + recognize 失败 → 30s 重试间隔里
    用户重画 → 第 2 轮 fetch image_hash=h2 → 检测到 hash 改变,退出,
    不再对老图 OCR。防 OCR(老图) 写到新图的 text 列。
    """
    from app.services.handwriting import ocr_task as ocr_task_mod

    img = _make_image(image_hash="h1")
    fetch_count = {"n": 0}

    @asynccontextmanager
    async def _ctx():
        sess = MagicMock()

        async def get(cls, pk):
            fetch_count["n"] += 1
            # 第 2 轮 fetch 模拟"用户在重试间隔里重画":image_hash 变了
            if fetch_count["n"] >= 2:
                img.image_hash = "h2"
                img.ocr_status = "pending"
                img.text = ""
            return img

        sess.get = get
        sess.commit = AsyncMock()
        yield sess

    monkeypatch.setattr(ocr_task_mod, "SessionLocal", _ctx)

    provider_called = {"n": 0}

    async def fake_recognize(*args, **kwargs):
        provider_called["n"] += 1
        raise RuntimeError("模拟第 1 轮失败")

    fake_provider = MagicMock()
    fake_provider.recognize = fake_recognize
    monkeypatch.setattr(ocr_task_mod, "get_handwriting_ocr", lambda: fake_provider)

    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        await real_sleep(0)

    monkeypatch.setattr(ocr_task_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr("app.services.sessions.runtime.registry.get", lambda sid: None)

    await ocr_task_mod._ocr_with_retry(image_id=42, session_id="s1")

    # 第 1 轮失败 → 进 sleep → 第 2 轮 fetch h2 → hash 改变 → 退出
    assert fetch_count["n"] == 2
    # provider 只被第 1 轮调(失败);第 2 轮发现 hash 变就退出,不重跑 OCR(老图)
    assert provider_called["n"] == 1
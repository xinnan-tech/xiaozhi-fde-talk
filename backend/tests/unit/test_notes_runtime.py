"""笔记注入 / 删除 / 持久化脏位单测。

覆盖:
- inject_keyboard_text 覆盖语义 + 触发 _dirty_notes
- inject_handwriting_note append + 按 image_id 幂等去重
- remove_handwriting_notes 同步清理 + 空集 no-op
- _flush_now 早退条件(纯 notes 脏也能落盘,不依赖 _dirty_segments)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.domain.session_state import HandwritingNoteSegment
from app.services.sessions.runtime import SessionRuntime


async def test_keyboard_inject_overwrites_and_dirties(make_state):
    """键盘注入覆盖 + 触发 _dirty_notes。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt._save_state = AsyncMock()
    # engine.on_note_added 在 _schedule_flush 之外调用;mock 防 engine 没初始化
    rt.engine.on_note_added = lambda: None

    await rt.inject_keyboard_text("第一次")
    assert rt.state.keyboard_text == "第一次"
    assert rt._dirty_notes is True

    await rt.inject_keyboard_text("第二次")
    assert rt.state.keyboard_text == "第二次"  # 覆盖语义


async def test_handwriting_inject_appends_and_dedups(make_state):
    """手写 append + 同 image_id 重入不重复 append。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt._save_state = AsyncMock()
    rt.engine.on_note_added = lambda: None

    await rt.inject_handwriting_note(image_id=1, text="ocr-A")
    await rt.inject_handwriting_note(image_id=2, text="ocr-B")
    # task 重入:image_id=1 再来一次不应追加第二段
    await rt.inject_handwriting_note(image_id=1, text="ocr-A")
    assert len(rt.state.handwriting_notes) == 2
    assert rt.state.handwriting_notes[0].image_id == 1
    assert rt.state.handwriting_notes[1].image_id == 2
    # injected_at 是 datetime,跨调用 timeout 会进位但语义不变
    assert isinstance(rt.state.handwriting_notes[0].injected_at, datetime)


async def test_handwriting_inject_sets_dirty_notes(make_state):
    """注入成功置 _dirty_notes=true;_flush_now 后续能落库。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt._save_state = AsyncMock()
    rt.engine.on_note_added = lambda: None

    assert rt._dirty_notes is False
    await rt.inject_handwriting_note(image_id=10, text="X")
    assert rt._dirty_notes is True


async def test_remove_handwriting_notes_dedupes(make_state):
    """删除手写图:按 image_id 集合从 state 同步移除 + 触发 _dirty_notes。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt._save_state = AsyncMock()
    rt.engine.on_note_added = lambda: None

    for i in range(3):
        await rt.inject_handwriting_note(image_id=i, text=f"ocr-{i}")
    assert len(rt.state.handwriting_notes) == 3

    # 删 image_id=1
    await rt.remove_handwriting_notes([1])
    remaining_ids = [e.image_id for e in rt.state.handwriting_notes]
    assert remaining_ids == [0, 2]


async def test_remove_handwriting_notes_empty_list_noop(make_state):
    """空 image_ids 列表 no-op,不 fire 防抖、不置 _dirty_notes。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt._save_state = AsyncMock()
    rt.engine.on_note_added = lambda: None

    # 先注入 1 条触发 dirty
    await rt.inject_handwriting_note(image_id=1, text="x")
    rt._dirty_notes = False  # 重置,只观察后续 no-op 是否不再 dirty

    # 空集 no-op:不应再次置 dirty
    await rt.remove_handwriting_notes([])
    assert rt._dirty_notes is False
    assert len(rt.state.handwriting_notes) == 1


async def test_remove_handwriting_notes_idempotent(make_state):
    """重复删同一个 image_id 第二次 no-op(已删)——不再额外 dirty。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    rt._save_state = AsyncMock()
    rt.engine.on_note_added = lambda: None

    await rt.inject_handwriting_note(image_id=1, text="x")
    await rt.remove_handwriting_notes([1])
    rt._dirty_notes = False  # 重置看后续

    # 再删同样 id:已不在列表,removed=0,不置 dirty
    await rt.remove_handwriting_notes([1])
    assert rt._dirty_notes is False


async def test_flush_now_writes_when_even_no_dirty_segments(make_state):
    """纯笔记脏(_dirty_segments==0 但 _dirty_notes=True)
    必须能触发落盘,而不是早退。

    旧实现下 _dirty_segments==0 时 _flush_now 直接 return,笔记永远落不进
    interviews.keyboard_text / interviews.handwriting_notes JSON 列。
    """
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    saved_fields: list = []

    async def save(*, fields=None):
        saved_fields.append(fields)

    rt._save_state = save
    rt.engine.on_note_added = lambda: None

    # 注入一条手写——这是唯一脏来源(无 ASR 句段)
    await rt.inject_handwriting_note(image_id=1, text="only-notes")

    # 模拟去抖定时器到期
    await rt._flush_now()

    assert len(saved_fields) == 1
    assert saved_fields[0] == {"notes"}  # 仅 notes 脏,只写 notes 分组


async def test_flush_now_short_circuits_when_neither_dirty(make_state):
    """segments 与 notes 都干净时 _flush_now 早退——避免空跑。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    saved: list = []

    async def save(*, fields=None):
        saved.append(True)

    rt._save_state = save
    rt.engine.on_note_added = lambda: None

    await rt._flush_now()
    assert saved == []


async def test_flush_now_combines_both_when_both_dirty(make_state):
    """transcript + notes 都脏 → 一次落盘 {"transcript", "notes"}。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    saved_fields: list = []

    async def save(*, fields=None):
        saved_fields.append(fields)

    rt._save_state = save
    rt.engine.on_note_added = lambda: None

    # 触发 ASR 句段(脏 transcript)
    await rt._on_utterance("你好", True, 16000)
    # 触发笔记(脏 notes)
    await rt.inject_handwriting_note(image_id=1, text="ocr")

    await rt._flush_now()
    assert len(saved_fields) == 1
    assert saved_fields[0] == {"transcript", "notes"}


async def test_persist_for_recompute_includes_notes(make_state):
    """P0-1:engine.on_note_added 触发的重算落盘必须含 notes 分组。

    旧实现只写 {"coaching"},笔记字段会被 engine 重算的 _save_state 跳过。
    """
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    saved_fields: list = []

    async def save(*, fields=None):
        saved_fields.append(fields)

    rt._save_state = save
    rt.engine.on_note_added = lambda: None

    # 注入笔记
    await rt.inject_handwriting_note(image_id=1, text="ocr")

    # engine 重算完成后调 _persist_for_recompute
    await rt._persist_for_recompute()

    assert {"coaching", "notes"} in saved_fields
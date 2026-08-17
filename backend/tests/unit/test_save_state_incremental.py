"""P2-8c · save_state 字段分组增量写，避免每次全列重序列化。

原 save_state 每次都重写 transcript + coaching_items + skipped/ignored/coverage，
即使本次只动了 transcript（utterance 去抖落盘）或只动了 coaching（重算落盘）。
transcript 在软上限内可达数百段，重算每轮全量重写 → 放大开销。

修复：save_state / save_state_auto 增 fields 形参（None=全写，供生命周期/兜底；
skip/ignore/shutdown/force_flush 仍全写，因 skip/ignore 直接改 coaching 组字段）；
runtime 按路径收窄：utterance 去抖落盘 → {"transcript"}；重算落盘 → {"coaching"}。
会话元信息（status/consumed_seq/timestamps 等）始终写，不在分组内。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.persistence.repositories.interview import InterviewRepository
from app.services.sessions.runtime import SessionRuntime


class _FakeRecord:
    """捕获属性写入，用于断言哪些列被改。"""

    def __init__(self, id_: str) -> None:
        object.__setattr__(self, "id", id_)
        object.__setattr__(self, "status", "in_progress")
        object.__setattr__(self, "writes", [])

    def __setattr__(self, attr: str, value) -> None:
        if attr not in ("id", "status", "writes"):
            self.writes.append(attr)
        object.__setattr__(self, attr, value)


class _FakeSession:
    def __init__(self, record) -> None:
        self._record = record

    async def get(self, cls, pk):  # noqa: ARG002
        return self._record

    def add(self, obj) -> None:
        self._record = obj

    async def commit(self) -> None:
        pass


@pytest.mark.asyncio
async def test_save_state_transcript_only_skips_coaching(make_state, make_seg):
    state = make_state()
    state.transcript.append(make_seg("s1", "t"))
    rec = _FakeRecord(state.session.id)
    await InterviewRepository().save_state(_FakeSession(rec), state, fields={"transcript"})
    assert "transcript" in rec.writes
    assert "coaching_items" not in rec.writes
    assert "coverage_index" not in rec.writes
    assert "skipped_ids" not in rec.writes


@pytest.mark.asyncio
async def test_save_state_coaching_only_skips_transcript(make_state, make_seg):
    state = make_state()
    state.transcript.append(make_seg("s1", "t"))
    rec = _FakeRecord(state.session.id)
    await InterviewRepository().save_state(_FakeSession(rec), state, fields={"coaching"})
    assert "coaching_items" in rec.writes
    assert "coverage_index" in rec.writes
    assert "ignored_ids" in rec.writes
    assert "transcript" not in rec.writes


@pytest.mark.asyncio
async def test_save_state_default_writes_all(make_state, make_seg):
    state = make_state()
    state.transcript.append(make_seg("s1", "t"))
    rec = _FakeRecord(state.session.id)
    await InterviewRepository().save_state(_FakeSession(rec), state)  # fields=None
    assert "transcript" in rec.writes
    assert "coaching_items" in rec.writes


@pytest.mark.asyncio
async def test_runtime_flush_now_passes_transcript_only(make_state):
    """utterance 去抖落盘应收窄到 transcript 分组。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    captured: dict = {}

    async def fake_save_state(*, fields=None):
        captured["fields"] = fields

    rt._save_state = fake_save_state
    rt._dirty_segments = 2
    await rt._flush_now()
    assert captured["fields"] == {"transcript"}


@pytest.mark.asyncio
async def test_runtime_persist_for_recompute_passes_coaching_only(make_state):
    """重算落盘应收窄到 coaching 分组。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    captured: dict = {}

    async def fake_save_state(*, fields=None):
        captured["fields"] = fields

    rt._save_state = fake_save_state
    await rt._persist_for_recompute()
    assert captured["fields"] == {"coaching"}


@pytest.mark.asyncio
async def test_runtime_skip_uses_full_save(make_state):
    """skip() 直接改 coaching 组字段，必须全写（fields=None），不能收窄。"""
    rt = SessionRuntime(make_state())
    rt._send_fn = AsyncMock()
    captured: dict = {}

    async def fake_save_state(*, fields=None):
        captured["fields"] = fields

    rt._save_state = fake_save_state
    await rt.skip("pain")
    assert captured["fields"] is None

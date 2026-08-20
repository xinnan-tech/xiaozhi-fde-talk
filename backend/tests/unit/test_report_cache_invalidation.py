"""报告缓存失效：transcript 变则重生。

回归需求：
- 已生成过 report + transcript 未变 → 返旧内容，不调 LLM
- 已生成过 report + transcript 变了 → 重新调 LLM
- 上次失败 → 重新调
- 旧行 transcript_signature 为空 → 视为失效，重生一次后填上
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.llm.base import LLMError
from app.domain.session import TranscriptSegment
from app.services.reports import generator
from app.services.reports.generator import _transcript_signature


def _seg(seg_id: str, text: str) -> TranscriptSegment:
    return TranscriptSegment(seg_id=seg_id, text=text, final=True, start_ms=0)


# --- 纯函数：transcript_signature ---

def test_signature_deterministic():
    """同样内容同样顺序 → 同样签名（dict 键排序后哈希）。"""
    segs = [_seg("s1", "你好"), _seg("s2", "世界")]
    assert _transcript_signature(segs) == _transcript_signature(list(segs))


def test_signature_order_matters():
    """段顺序变了 → 签名变（顺序语义：先来后到）。"""
    a = [_seg("s1", "你好"), _seg("s2", "世界")]
    b = [_seg("s2", "世界"), _seg("s1", "你好")]
    assert _transcript_signature(a) != _transcript_signature(b)


def test_signature_changes_when_text_changes():
    base = [_seg("s1", "你好")]
    edited = [_seg("s1", "你好呀")]
    assert _transcript_signature(base) != _transcript_signature(edited)


def test_signature_changes_when_segment_added():
    base = [_seg("s1", "你好")]
    added = [_seg("s1", "你好"), _seg("s2", "世界")]
    assert _transcript_signature(base) != _transcript_signature(added)


def test_signature_handles_chinese():
    sig = _transcript_signature([_seg("s1", "中文+iPad+；标点")])
    assert isinstance(sig, str) and len(sig) == 16


# --- get_or_generate：缓存命中 / 失效 ---

@dataclass
class _FakeState:
    transcript: list[TranscriptSegment] = field(default_factory=list)
    session: MagicMock = field(default_factory=lambda: MagicMock(template_id="pm-research"))


@dataclass
class _FakeRec:
    status: str = "ready"
    content_md: str = ""
    transcript_signature: str = ""
    output_language: str = ""


@pytest.mark.asyncio
async def test_cache_hit_same_transcript(monkeypatch):
    """transcript 未变 → 返旧内容，不调 LLM。"""
    segs = [_seg("s1", "你好")]
    state = _FakeState(transcript=segs)
    sig = _transcript_signature(segs)

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=_FakeRec(
            status="ready", content_md="cached content",
            transcript_signature=sig, output_language="zh_cn",
        )),
        upsert_auto=AsyncMock(),
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock()
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "get_template", lambda _id: MagicMock(report=MagicMock(doc="")))

    status, md = await generator.get_or_generate("s1")

    assert status == "ready"
    assert md == "cached content"
    llm.chat_text.assert_not_called()
    generator.report_repo.upsert_auto.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_transcript_changed(monkeypatch):
    """transcript 变了 → 重生 + 落库 + 更新指纹。"""
    state = _FakeState(transcript=[_seg("s1", "新文本")])
    new_sig = _transcript_signature(state.transcript)

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    upsert_mock = AsyncMock()
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=_FakeRec(
            status="ready", content_md="old content", transcript_signature="different-sig",
        )),
        upsert_auto=upsert_mock,
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock(return_value="new content")
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "get_template", lambda _id: MagicMock(report=MagicMock(doc="")))
    monkeypatch.setattr(generator, "render_skills", AsyncMock(side_effect=lambda m: m))

    status, md = await generator.get_or_generate("s1")

    assert status == "ready"
    assert md == "new content"
    llm.chat_text.assert_awaited_once()
    upsert_mock.assert_awaited_once()
    # 关键：upsert 时传了新的 transcript_signature
    _, kwargs = upsert_mock.call_args
    args = upsert_mock.call_args.args
    assert args[2] == "ready"  # status
    assert kwargs.get("transcript_signature") == new_sig


@pytest.mark.asyncio
async def test_cache_miss_legacy_empty_signature(monkeypatch):
    """旧行 transcript_signature 为空 → 视为失效，重生一次。"""
    state = _FakeState(transcript=[_seg("s1", "text")])

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=_FakeRec(
            status="ready", content_md="old", transcript_signature="",
        )),
        upsert_auto=AsyncMock(),
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock(return_value="fresh")
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "get_template", lambda _id: MagicMock(report=MagicMock(doc="")))
    monkeypatch.setattr(generator, "render_skills", AsyncMock(side_effect=lambda m: m))

    status, md = await generator.get_or_generate("s1")
    assert status == "ready"
    assert md == "fresh"


@pytest.mark.asyncio
async def test_cache_miss_status_failed(monkeypatch):
    """上次失败 → 重生。"""
    state = _FakeState(transcript=[_seg("s1", "x")])
    sig = _transcript_signature(state.transcript)

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=_FakeRec(
            status="failed", content_md="", transcript_signature=sig,
        )),
        upsert_auto=AsyncMock(),
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock(return_value="regenerated")
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "get_template", lambda _id: MagicMock(report=MagicMock(doc="")))
    monkeypatch.setattr(generator, "render_skills", AsyncMock(side_effect=lambda m: m))

    status, md = await generator.get_or_generate("s1")
    assert md == "regenerated"


@pytest.mark.asyncio
async def test_llm_failure_keeps_failed_status(monkeypatch):
    """LLM 抛错 → status=failed, 落库（覆盖 ready 旧值）。

    配缓存 miss（transcript 变了）：触发重生 → LLM 抛 → 标 failed 落库。
    """
    state = _FakeState(transcript=[_seg("s1", "x")])

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    upsert_mock = AsyncMock()
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        # 缓存的 sig 与当前 transcript 的 sig 不匹配 → 走重生路径
        get_by_interview_auto=AsyncMock(return_value=_FakeRec(
            status="ready", content_md="stale", transcript_signature="old-sig",
        )),
        upsert_auto=upsert_mock,
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock(side_effect=LLMError("network down"))
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "get_template", lambda _id: MagicMock(report=MagicMock(doc="")))

    status, md = await generator.get_or_generate("s1")
    assert status == "failed"
    assert md == ""
    upsert_mock.assert_awaited_once()
    assert upsert_mock.call_args.args[2] == "failed"
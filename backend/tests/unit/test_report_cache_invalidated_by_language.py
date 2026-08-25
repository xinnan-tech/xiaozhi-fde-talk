"""报告缓存按语种失效：语种变了 → 重生；语种相同 → 命中。

回归需求：
- 缓存行 output_language 与当前 llm.output_language 不一致 → 强制重生（覆盖旧报告）
- 缓存行 output_language 与当前一致 → 命中，不调 LLM
- 旧行（output_language 为空字符串）→ 视为未标，定失效
- get_or_generate 只读一次 ConfigStore（消除 cache 标 post-flip / content pre-flip 的 race）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.session import TranscriptSegment
from app.services.reports import generator
from app.services.reports.generator import _transcript_signature


def _seg(seg_id: str, text: str) -> TranscriptSegment:
    return TranscriptSegment(seg_id=seg_id, text=text, final=True, start_ms=0)


@dataclass
class _FakeState:
    transcript: list[TranscriptSegment] = field(default_factory=list)
    session: MagicMock = field(default_factory=lambda: MagicMock(template_id="pm-research"))
    items: list = field(default_factory=list)  # _build_user reads state.items


@dataclass
class _FakeRec:
    status: str = "ready"
    content_md: str = ""
    transcript_signature: str = ""
    output_language: str = ""


def _patch_config(monkeypatch, language: str) -> list:
    """把 ConfigStore 桩成单一固定语种，并返回 get_sync 计数 spy。"""
    store = MagicMock()
    spy: list[str] = []

    def _get_sync(key, default=None):
        spy.append(key)
        if key == "llm.output_language":
            return language
        return default

    store.get_sync = _get_sync
    monkeypatch.setattr(generator, "get_config_store", lambda: store)
    return spy


async def test_cache_miss_when_language_changed(monkeypatch):
    """缓存行 output_language=zh_cn 但当前配置 en → 失效 → 重生 + 落 en。"""
    segs = [_seg("s1", "你好")]
    state = _FakeState(transcript=segs)
    sig = _transcript_signature(segs)
    _patch_config(monkeypatch, "en")

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    upsert_mock = AsyncMock()
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=_FakeRec(
            status="ready", content_md="old chinese report",
            transcript_signature=sig, output_language="zh_cn",
        )),
        upsert_auto=upsert_mock,
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock(return_value="new english report")
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "get_template", lambda _id: MagicMock(report=MagicMock(doc="")))
    monkeypatch.setattr(generator, "render_skills", AsyncMock(side_effect=lambda m: m))

    status, md = await generator.get_or_generate("s1")

    assert status == "ready"
    assert md == "new english report"
    llm.chat_text.assert_awaited_once()
    upsert_mock.assert_awaited_once()
    _, kwargs = upsert_mock.call_args
    assert kwargs.get("output_language") == "en", (
        f"upsert 应落当前语种 en，实际 {kwargs.get('output_language')!r}"
    )


async def test_cache_hit_when_language_matches(monkeypatch):
    """缓存行 output_language=en 且当前配置 en → 命中，LLM 不调。"""
    segs = [_seg("s1", "你好")]
    state = _FakeState(transcript=segs)
    sig = _transcript_signature(segs)
    _patch_config(monkeypatch, "en")

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=_FakeRec(
            status="ready", content_md="cached english report",
            transcript_signature=sig, output_language="en",
        )),
        upsert_auto=AsyncMock(),
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock()
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "get_template", lambda _id: MagicMock(report=MagicMock(doc="")))
    monkeypatch.setattr(generator, "render_skills", AsyncMock(side_effect=lambda m: m))

    status, md = await generator.get_or_generate("s1")

    assert status == "ready"
    assert md == "cached english report"
    llm.chat_text.assert_not_called()
    generator.report_repo.upsert_auto.assert_not_called()


async def test_legacy_empty_output_language_forced_regen(monkeypatch):
    """旧行 output_language=''（迁移前）→ 视为未标，必须重生。"""
    segs = [_seg("s1", "你好")]
    state = _FakeState(transcript=segs)
    sig = _transcript_signature(segs)
    _patch_config(monkeypatch, "zh_cn")  # 即便语种未动也强制

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=_FakeRec(
            status="ready", content_md="legacy report",
            transcript_signature=sig, output_language="",
        )),
        upsert_auto=AsyncMock(),
    ))
    llm = MagicMock()
    # mock 返回含 zh_cn 字符——避免 pivot 误触发；production zh_cn 报告含中文。
    llm.chat_text = AsyncMock(return_value="## 背景与目的\n新报告内容")
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "get_template", lambda _id: MagicMock(report=MagicMock(doc="")))
    monkeypatch.setattr(generator, "render_skills", AsyncMock(side_effect=lambda m: m))

    status, md = await generator.get_or_generate("s1")

    assert md == "## 背景与目的\n新报告内容"
    llm.chat_text.assert_awaited_once()


async def test_get_or_generate_reads_language_once(monkeypatch):
    """get_or_generate 只读一次 ConfigStore，generate_report 不再重读。

    消除 race：原先两处都调 get_sync，期间 admin 改了语种 → cache 标 post-flip、
    content pre-flip，报告内容与缓存标签不一致（且下次请求按新语种继续命中）。
    """
    segs = [_seg("s1", "你好")]
    state = _FakeState(transcript=segs)
    sig = _transcript_signature(segs)
    spy = _patch_config(monkeypatch, "zh_cn")

    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    monkeypatch.setattr(generator, "report_repo", MagicMock(
        get_by_interview_auto=AsyncMock(return_value=None),  # 强制走生成
        upsert_auto=AsyncMock(),
    ))
    llm = MagicMock()
    llm.chat_text = AsyncMock(return_value="new report")
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "get_template", lambda _id: MagicMock(report=MagicMock(doc="")))
    monkeypatch.setattr(generator, "render_skills", AsyncMock(side_effect=lambda m: m))

    await generator.get_or_generate("s1")

    read_keys = [k for k in spy if k == "llm.output_language"]
    assert len(read_keys) == 1, (
        f"ConfigStore 读 llm.output_language 应只有 1 次，实际 {len(read_keys)} 次：{spy}"
    )

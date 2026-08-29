"""报告生成 single-flight 回归。

同一 interview 的并发首次生成（10s LLM 窗口内重复点「查看报告」），
应只调一次 LLM、落一次库；后到的请求等锁后命中缓存直接返回。
不同 interview 互不阻塞（锁按 session 隔离）。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

from app.domain.session import TranscriptSegment
from app.services.reports import generator
from app.services.reports.generator import _transcript_signature


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


class _FakeReportRepo:
    """带状态的 report 仓库桩：upsert 后 get 能读到刚写的行（模拟真库）。"""

    def __init__(self) -> None:
        self.rec: _FakeRec | None = None
        self.upserts = 0

    async def get_by_interview_auto(self, session_id: str):
        return self.rec

    async def upsert_auto(self, session_id, md, status, transcript_signature="", output_language=""):
        self.upserts += 1
        self.rec = _FakeRec(
            status=status, content_md=md, transcript_signature=transcript_signature,
            output_language=output_language,
        )


def _patch_deps(monkeypatch, repo, llm_calls: list[str]):
    state = _FakeState(transcript=[
        TranscriptSegment(seg_id="s1", text="你好", final=True, start_ms=0),
    ])
    monkeypatch.setattr(generator, "interview_repo", MagicMock(
        get_state_auto=AsyncMock(return_value=state),
    ))
    monkeypatch.setattr(generator, "report_repo", repo)

    async def _slow_chat(system, user):
        await asyncio.sleep(0.05)  # 拉长窗口，让并发请求都聚到这里
        llm_calls.append("call")
        # 含 zh_cn 字符——避免 zh_cn 配置下 pivot 误触发；production 真实报告是中文。
        return "## 背景与目的\n生成的报告内容"

    llm = MagicMock()
    llm.chat_text = _slow_chat
    monkeypatch.setattr(generator, "get_llm", lambda: llm)
    monkeypatch.setattr(generator, "resolve_template", lambda _id, _snap: MagicMock(report=MagicMock(doc="")))
    monkeypatch.setattr(generator, "render_skills", AsyncMock(side_effect=lambda m: m))


async def test_concurrent_generate_calls_llm_once(monkeypatch):
    """同一 session 并发 3 次首次生成 → LLM 只调 1 次，3 个结果一致。"""
    repo = _FakeReportRepo()
    llm_calls: list[str] = []
    _patch_deps(monkeypatch, repo, llm_calls)
    sig = _transcript_signature([TranscriptSegment(seg_id="s1", text="你好", final=True, start_ms=0)])

    results = await asyncio.gather(*[generator.get_or_generate("sf-1") for _ in range(3)])

    assert len(llm_calls) == 1, f"并发应只调一次 LLM，实际 {len(llm_calls)} 次"
    assert repo.upserts == 1
    assert results == [("ready", "## 背景与目的\n生成的报告内容")] * 3
    assert repo.rec.transcript_signature == sig


async def test_lock_is_per_session(monkeypatch):
    """不同 session 并发生成互不阻塞 → 各调一次 LLM。"""
    repo = _FakeReportRepo()
    llm_calls: list[str] = []
    _patch_deps(monkeypatch, repo, llm_calls)

    await asyncio.gather(
        generator.get_or_generate("sf-a"),
        generator.get_or_generate("sf-b"),
    )

    assert len(llm_calls) == 2, "不同 session 不应共享锁串行"

"""快照隔离：编辑/删除模板不影响已创建访谈的模板读取。"""
from __future__ import annotations

import pytest

from app.domain.session import Session
from app.domain.session_state import SessionState
from app.domain.template import Template
from app.services.template import loader


@pytest.fixture(autouse=True)
def _pop_cache_residue():
    """测试往进程级 loader._cache 写 snap-t1，结束后清掉，不泄漏给后续模块。"""
    yield
    loader._cache.pop("snap-t1", None)


def _tpl(tid: str = "snap-t1") -> Template:
    return Template(
        id=tid, name="快照测试", version="3",
        session={"name": "s", "goal": "", "base_fields": [], "setup": {}},
        coaching={"playbook": "", "must_ask": [
            {"id": "q1", "text": "旧问题"},
        ]},
        report={"doc": ""},
    )


def test_resolve_prefers_snapshot_over_edited_template():
    """缓存里模板已改（模拟编辑后），带快照的会话仍读旧版。"""
    old = _tpl()
    session = Session(
        id="s1", user_id="u1", template_id="snap-t1",
        template_snapshot=old.model_dump(mode="json"),
    )
    # 当前缓存换成新版（must_ask 变了）
    loader._cache["snap-t1"] = _tpl().model_copy(deep=True)
    loader._cache["snap-t1"].coaching.must_ask[0].text = "新问题"

    resolved = loader.resolve_template(session.template_id, session.template_snapshot)
    assert resolved.coaching.must_ask[0].text == "旧问题"
    assert resolved.version == "3"


def test_null_snapshot_falls_back_to_current():
    session = Session(id="s2", user_id="u1", template_id="pm-research")
    resolved = loader.resolve_template(session.template_id, session.template_snapshot)
    assert resolved is not None and resolved.id == "pm-research"


def test_initial_state_from_snapshot_template():
    """SessionState.initial 用快照模板种 must_ask 占位（引擎首算前的种子）。"""
    session = Session(
        id="s3", user_id="u1", template_id="snap-t1",
        template_snapshot=_tpl().model_dump(mode="json"),
    )
    state = SessionState.initial(session, loader.resolve_template(
        session.template_id, session.template_snapshot))
    assert [i.text for i in state.items] == ["旧问题"]

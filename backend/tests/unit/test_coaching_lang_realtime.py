"""coaching engine：每次 _recompute / first_generate 都从 ConfigStore 现读
llm.output_language，而不是用 self._output_language（ainit 一次性缓存会导致
管理员改语种后旧 session 一直沿用旧值，直到结束才切）。

测试用 async def（项目 pytest.ini asyncio_mode=auto）—— 同一 loop 下连续 await，
避免 asyncio.Lock 跨 loop 抛 RuntimeError: ... is bound to a different event loop。
"""
from unittest.mock import MagicMock

from app.domain.session import Session
from app.domain.template import CoachingBlock, Template
from app.services.coaching.engine import CoachingEngine
from app.services.sessions.state import SessionState


async def _noop_send(_msg):
    return None


async def _noop_async(*_a, **_k):
    return None


def _async_return(value):
    async def _f(*_a, **_k):
        return value
    return _f


def _make_engine():
    """构造一个最小可用 CoachingEngine；不调 ainit（测试场景不需要 LLM）。"""
    tpl = Template(id="t1", version="1", name="t", icon_alt="",
                   coaching=CoachingBlock(playbook="", must_ask=[]))
    # 模板经 template_snapshot 注入：CoachingEngine.__init__ 里
    # resolve_template 返 None 会直接抛 RuntimeError（模板缺失是配置错误），
    # 而 "t1" 不在 loader 缓存里。走 snapshot 比改全局 loader._cache 干净——
    # 无需清理、不跨测试泄漏。本用例只验证 output_language 现读，模板内容无关。
    sess = Session(
        id="sid", template_id="t1", template_version="1", user_id="u",
        status="in_progress", base_info={}, goal="", created_at=None,
        started_at=None, ended_at=None,
        template_snapshot=tpl.model_dump(mode="json"),
    )
    state = SessionState(session=sess, items=[], transcript=[])
    eng = CoachingEngine(state, _noop_send)
    eng.version = 0
    # _recompute / first_generate 入口都有 `if self._llm is None: raise`，缺这行
    # 会在 await 的第一帧抛 RuntimeError，spy 永远抓不到 build_system 调用。
    # 真 LLM 不会被调到——_llm_pivot_then_parse_json 已被 monkeypatch 替换，
    # _llm 仅用作哨兵。
    eng._llm = MagicMock()
    return eng


async def test_recompute_reads_current_lang_each_call(monkeypatch):
    """两次 _recompute，ConfigStore 在中间改了值 → 第二次看到新值。"""
    eng = _make_engine()

    cfg = MagicMock()
    cfg.get_sync.return_value = "en"
    # _read_output_language 在函数体内做 `from app.core.config_store import get_config_store`，
    # 所以这里必须 patch 原模块的属性（不是 engine 模块的——那里没有这个名）。
    monkeypatch.setattr(
        "app.core.config_store.get_config_store", lambda: cfg)

    monkeypatch.setattr(eng, "_llm_pivot_then_parse_json",
                        _async_return({"items": []}))
    monkeypatch.setattr(eng, "_persist", _noop_async)
    monkeypatch.setattr(eng, "_safe_send", _noop_async)

    captured = []
    import app.services.coaching.engine as engine_mod

    def spy_build_system(template, goal, output_language="zh_cn"):
        captured.append(output_language)
        return "SYSTEM"

    monkeypatch.setattr(engine_mod, "build_system", spy_build_system)

    cfg.get_sync.return_value = "en"
    await eng._recompute()
    assert captured == ["en"], captured

    cfg.get_sync.return_value = "zh_cn"
    await eng._recompute()
    assert captured == ["en", "zh_cn"], captured


async def test_first_generate_reads_current_lang(monkeypatch):
    """first_generate 走 build_first_batch（不是 build_system），独立验证路径。

    注意：first_generate 是「每会话只跑一次」——第二次调用会因守卫
    `if self.state.session.first_batch_generated: return` 早退，build_first_batch
    不会被再调用。所以这里用两个 fresh engine 各跑一次，对应"admin 改语种 →
    新 session 立即生效"的真实场景。
    """
    cfg = MagicMock()
    cfg.get_sync.return_value = "en"
    # _read_output_language 在函数体内做 `from app.core.config_store import get_config_store`，
    # 所以这里必须 patch 原模块的属性（不是 engine 模块的——那里没有这个名）。
    monkeypatch.setattr(
        "app.core.config_store.get_config_store", lambda: cfg)

    captured = []
    import app.services.coaching.engine as engine_mod

    def spy_first_batch(template, session, output_language="zh_cn"):
        captured.append(output_language)
        return "SYSTEM", "USER"

    monkeypatch.setattr(engine_mod, "build_first_batch", spy_first_batch)

    cfg.get_sync.return_value = "en"
    eng1 = _make_engine()
    monkeypatch.setattr(eng1, "_llm_pivot_then_parse_json",
                        _async_return({"items": []}))
    monkeypatch.setattr(eng1, "_persist", _noop_async)
    monkeypatch.setattr(eng1, "_safe_send", _noop_async)
    await eng1.first_generate()
    assert captured == ["en"], captured

    cfg.get_sync.return_value = "zh_tw"
    eng2 = _make_engine()
    monkeypatch.setattr(eng2, "_llm_pivot_then_parse_json",
                        _async_return({"items": []}))
    monkeypatch.setattr(eng2, "_persist", _noop_async)
    monkeypatch.setattr(eng2, "_safe_send", _noop_async)
    await eng2.first_generate()
    assert captured == ["en", "zh_tw"], captured

"""Stage 5 prompt 修订回归测试：

- format 注入防护（goal 含 `{xxx}` 不再 KeyError）
- first_batch 系统 prompt 模板化（playbook 集中维护）
- fallback_phrase 并入 LangMeta（单源）
- assert msg 不再引用已删的 _REPORT_LANG_INSTRUCTION
- _fill_dangling_labels 默认 en 兜底
- 空 goal 时主句不撒谎（"The goal has been provided" → "use the must_ask baseline"）
- user 尾句英文化
- _STYLE_RULE_BASE CJK 字符歧义说明（~30 chars for CJK languages）
"""
from __future__ import annotations

import pytest

from app.core.i18n.lang_meta import (
    _LANG_META,
    derived_fallback_phrases,
    get_lang_meta,
)
from app.domain.session import Session
from app.services.coaching.prompt import (
    _STYLE_RULE_BASE,
    build_first_batch,
    build_system,
    build_user,
)
from app.services.reports.generator import _fill_dangling_labels
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template


# ── format 注入防护 ──────────────────────────────────────


def test_build_system_survives_braces_in_goal():
    """goal 含 `{华东}` 不再 KeyError——format 与动态内容拼接顺序解耦。"""
    tpl = get_template("pm-research")
    system = build_system(tpl, "搞清{华东}库存痛点", "zh_cn")
    # goal 内容应通过 XML 转义保留在 <user_goal> 块里
    assert "{华东}" in system or "&lt;user_goal&gt;" in system or "华东" in system


def test_build_first_batch_survives_braces_in_goal():
    tpl = get_template("pm-research")
    session = Session(id="s1", template_id="pm-research",
                      base_info={"project": "P"}, goal="搞清{华东}库存")
    system, _user = build_first_batch(tpl, session, "zh_cn")
    assert "华东" in system or "{华东}" in system


def test_build_system_survives_braces_in_playbook():
    """模板 playbook 含 `{placeholder}` 也不爆。"""
    from app.domain.template import CoachingBlock, Template

    tpl = Template(
        id="t1", version="1", name="t", icon_alt="",
        session={"goal": "", "base_fields": [], "setup": {}},
        coaching=CoachingBlock(
            playbook="规则：填 {项目背景}，避免 {敏感词}",
            must_ask=[],
        ),
        report={"doc": ""},
    )
    system = build_system(tpl, "目标", "zh_cn")
    assert "{项目背景}" in system


# ── first_batch 系统 prompt 模板化 ─────────────────────


def test_build_first_batch_includes_template_playbook():
    from app.domain.template import CoachingBlock, Template

    tpl = Template(
        id="t1", version="1", name="t", icon_alt="",
        session={"goal": "", "base_fields": [], "setup": {}},
        coaching=CoachingBlock(
            playbook="独特提问风格：用'能不能'开场，不要'会不会'",
            must_ask=[],
        ),
        report={"doc": ""},
    )
    session = Session(id="s1", template_id="t1", base_info={}, goal="目标")
    system, _ = build_first_batch(tpl, session, "zh_cn")
    assert "独特提问风格" in system
    assert "&lt;template_playbook&gt;" in system or "<template_playbook>" in system


def test_build_system_includes_template_playbook():
    """回归保护：build_system 一直含 playbook。"""
    from app.domain.template import CoachingBlock, Template

    tpl = Template(
        id="t1", version="1", name="t", icon_alt="",
        session={"goal": "", "base_fields": [], "setup": {}},
        coaching=CoachingBlock(
            playbook="PLAYBOOK_MARKER_XYZ",
            must_ask=[],
        ),
        report={"doc": ""},
    )
    system = build_system(tpl, "目标", "zh_cn")
    assert "PLAYBOOK_MARKER_XYZ" in system


# ── fallback_phrase 并入 LangMeta（单源）────────────────


def test_lang_meta_fallback_phrase_unified_source():
    """derived_fallback_phrases 必须从 LangMeta.fallback_phrase 派生——加语种只改一处。"""
    phrases = derived_fallback_phrases()
    assert set(phrases) == set(_LANG_META)
    for lang, meta in _LANG_META.items():
        assert phrases[lang] == meta.fallback_phrase, (
            f"{lang}: phrases[{lang!r}]={phrases[lang]!r} vs "
            f"meta.fallback_phrase={meta.fallback_phrase!r}"
        )


def test_lang_meta_all_ten_have_fallback_phrase():
    """头部 10 语种每条 LangMeta 必须有 fallback_phrase。"""
    assert len(_LANG_META) == 10
    for lang, meta in _LANG_META.items():
        assert isinstance(meta.fallback_phrase, str) and meta.fallback_phrase, (
            f"{lang} 缺 fallback_phrase"
        )


# ── assert msg 不再引用已删 _REPORT_LANG_INSTRUCTION ─────────


def test_generator_assert_message_no_dead_reference():
    """import 期评估 assert cond 不炸——cond 必为 True（10 语种键集合相等）。

    即便 cond=True（不触发 msg），也保护 future 改动不会因 stale 引用 import 期失败。
    """
    import app.services.reports.generator as gen_mod
    # 强制重 import 触 assert——msg 是 lazy 求值，import 阶段只算 cond。
    import importlib
    importlib.reload(gen_mod)
    assert set(gen_mod._FALLBACK_BY_LANG) == set(_LANG_META)


# ── _fill_dangling_labels 默认 en 兜底────────


def test_fill_dangling_labels_default_uses_en_fallback():
    """不传 language → 默认 en 兜底短语（消除英文报告被注入中文的隐性 bug）。"""
    md = "- 标签：\n"
    out = _fill_dangling_labels(md)
    # en 兜底短语：'Not mentioned in this interview.'
    assert "Not mentioned in this interview" in out
    # 不能再是中文兜底短语
    assert "本次访谈未提及" not in out


def test_fill_dangling_labels_zh_cn_explicit_still_works():
    """显式传 zh_cn 仍走中文短语——保持现有 zh_cn 路径不变。"""
    md = "- 标签：\n"
    out = _fill_dangling_labels(md, language="zh_cn")
    assert "本次访谈未提及" in out


# ── 空 goal 时主句不撒谎 ────────────────────────────────


def test_build_system_empty_goal_uses_baseline_clause():
    """空 goal 时不写 'The goal has been provided'——改成 'use the must_ask baseline'。"""
    tpl = get_template("pm-research")
    system = build_system(tpl, None, "zh_cn")
    assert "The goal has been provided" not in system
    assert "must_ask baseline" in system


def test_build_system_empty_string_goal_same_as_none():
    tpl = get_template("pm-research")
    system = build_system(tpl, "   ", "zh_cn")
    assert "The goal has been provided" not in system


def test_build_first_batch_empty_goal_uses_baseline_clause():
    tpl = get_template("pm-research")
    session = Session(id="s1", template_id="pm-research", base_info={}, goal="")
    system, _ = build_first_batch(tpl, session, "zh_cn")
    assert "The goal has been provided" not in system


def test_build_system_with_goal_still_announces_goal():
    """有 goal 时仍写 'The goal has been provided'——正常路径不变。"""
    tpl = get_template("pm-research")
    system = build_system(tpl, "目标：搞清库存痛点", "zh_cn")
    assert "The goal has been provided" in system


# ── user 尾句英文化 ────────────────────


def test_build_user_tail_is_english():
    """user 尾句不再用「请输出…」中文——非 zh_cn user 阅读违和。"""
    sess = Session(id="s1", template_id="pm-research", base_info={}, goal="")
    state = SessionState(session=sess, items=[], transcript=[])
    user = build_user(state)
    assert "请输出" not in user
    assert "Output the updated complete list now" in user


def test_build_first_batch_user_tail_is_english():
    tpl = get_template("pm-research")
    session = Session(id="s1", template_id="pm-research", base_info={}, goal="目标")
    _sys, user = build_first_batch(tpl, session, "zh_cn")
    assert "请输出" not in user
    assert "Output the opening batch of interview questions now" in user


# ── CJK 字符歧义说明 ──────────────────────────────────


def test_style_rule_base_clarifies_cjk_word_vs_character():
    """~20 words 对 CJK 歧义——加「~30 characters for CJK languages」说明。"""
    assert "~30 characters for CJK languages" in _STYLE_RULE_BASE


# ── 跨平台 sanity：get_lang_meta + fallback_phrase 仍工作 ──────────


def test_get_lang_meta_returns_meta_with_fallback_phrase():
    """get_lang_meta 返回的 LangMeta 仍带 fallback_phrase 字段。"""
    meta = get_lang_meta("zh_cn")
    assert meta.fallback_phrase == "本次访谈未提及"
    meta = get_lang_meta("en")
    assert meta.fallback_phrase == "Not mentioned in this interview."
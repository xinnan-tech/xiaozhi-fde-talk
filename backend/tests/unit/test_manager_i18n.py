"""Sessions manager named I18nError subclasses: code + localized message per locale.

manager.py raises these in place of legacy ConcurrentLimitError /
IllegalTransitionError / etc. Tests verify each subclass carries the correct
Keys.* code and renders the expected en-US / zh-CN / zh-TW text.
"""
from __future__ import annotations

import pytest
from app.services.sessions.manager import (
    SessionConcurrentLimitError,
    SessionIllegalTransitionError,
    SessionEditForbiddenError,
    SessionDeleteForbiddenError,
)
from app.core.i18n.messages import Keys


def test_concurrent_limit_key():
    e = SessionConcurrentLimitError(limit=3)
    assert e.code == Keys.SESSION_CONCURRENT_LIMIT.value
    assert e.localized(locale="en-US") == "Active interview limit reached (3)"
    assert e.localized(locale="zh-CN") == "活跃访谈数已达上限（3）"
    assert e.localized(locale="zh-TW") == "活躍訪談數已達上限（3）"


def test_illegal_transition_keys():
    e = SessionIllegalTransitionError(from_state="ended", to_state="in_progress")
    assert e.code == Keys.SESSION_ILLEGAL_TRANSITION.value
    assert e.localized(locale="en-US") == "Illegal state transition: ended → in_progress"
    assert e.localized(locale="zh-CN") == "非法状态转换：ended → in_progress"
    assert e.localized(locale="zh-TW") == "非法狀態轉換：ended → in_progress"


def test_edit_and_delete_forbidden():
    e1 = SessionEditForbiddenError(state="in_progress")
    assert e1.localized(locale="en-US") == "Interview in state in_progress cannot be edited"
    assert e1.localized(locale="zh-CN") == "当前状态（in_progress）不可编辑"
    assert e1.localized(locale="zh-TW") == "當前狀態（in_progress）不可編輯"
    e2 = SessionDeleteForbiddenError(state="active")
    assert e2.localized(locale="en-US") == "Interview in state active cannot be deleted"
    assert e2.localized(locale="zh-CN") == "当前状态（active）不可删除"
    assert e2.localized(locale="zh-TW") == "當前狀態（active）不可刪除"

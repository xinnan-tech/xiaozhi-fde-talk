"""_resolve_interviewee 启发式回落：自定义模板人物字段不叫 interviewee 也能上首页卡。

回归 issue #120：原实现硬编码 base_info.get('interviewee', '')，自定义模板
只要人物字段不是 `interviewee` 这个键就首页显示 --。修复后按模板 base_fields
声明顺序找首个非空 text 字段作为受访者展示。
"""
from __future__ import annotations

import pytest

from app.domain.template import BaseField, SetupBlock, SessionBlock, Template
from app.transport.http.routes.interviews import _resolve_interviewee


def _tpl(*fields: BaseField) -> Template:
    """构造一个最小模板，只关心 base_fields。"""
    return Template(
        id="t", name="t", version="1",
        session=SessionBlock(
            base_fields=list(fields),
            setup=SetupBlock(),
        ),
        coaching={"must_ask": []},
        report={"doc": ""},
    )


def test_prefers_named_interviewee_field():
    """直取 base_info['interviewee']——历史约定优先保留。"""
    tpl = _tpl(
        BaseField(key="interviewee", label="受访者", type="text"),
        BaseField(key="customer_name", label="客户名", type="text"),
    )
    base_info = {"interviewee": "张三", "customer_name": "李四"}
    assert _resolve_interviewee(base_info, tpl) == "张三"


def test_fallback_to_first_text_field_when_interviewee_missing():
    """回归 issue #120 核心场景：custom 模板人物字段叫 customer_name。"""
    tpl = _tpl(
        BaseField(key="customer_name", label="客户名", type="text"),
        BaseField(key="order_no", label="单号", type="text"),
    )
    base_info = {"customer_name": "张三", "order_no": "A001"}
    assert _resolve_interviewee(base_info, tpl) == "张三"


def test_fallback_skips_empty_text_fields():
    """首个 text 字段值为空 → 继续往后找；datetime/duration 永不参与。"""
    tpl = _tpl(
        BaseField(key="visit_time", label="回访时间", type="datetime"),
        BaseField(key="customer_name", label="客户名", type="text"),  # 空
        BaseField(key="fallback", label="兜底", type="text"),
    )
    base_info = {"customer_name": "", "fallback": "李四"}
    assert _resolve_interviewee(base_info, tpl) == "李四"


def test_fallback_skips_non_text_field_types():
    """datetime/duration 字段即使有值也不充当 interviewee（语义不对）。"""
    tpl = _tpl(
        BaseField(key="visit_time", label="回访时间", type="datetime"),
        BaseField(key="customer_name", label="客户名", type="text"),
    )
    base_info = {"visit_time": "2026-08-25", "customer_name": "王五"}
    assert _resolve_interviewee(base_info, tpl) == "王五"


def test_returns_empty_when_no_text_field_has_value():
    """text 字段都为空 → 返回空串，让前端 -- fallback。"""
    tpl = _tpl(
        BaseField(key="customer_name", label="客户名", type="text"),
        BaseField(key="phone", label="电话", type="text"),
    )
    assert _resolve_interviewee({"customer_name": "", "phone": None}, tpl) == ""


def test_returns_empty_when_template_missing():
    """tpl=None 时不应崩——保持前端 fallback 一致。"""
    assert _resolve_interviewee({"foo": "bar"}, None) == ""


def test_interviewee_key_with_only_whitespace_falls_back():
    """interviewee 字段值是纯空白 → 不算命中，启发式继续。"""
    tpl = _tpl(
        BaseField(key="interviewee", label="受访者", type="text"),
        BaseField(key="customer_name", label="客户名", type="text"),
    )
    base_info = {"interviewee": "   ", "customer_name": "张三"}
    assert _resolve_interviewee(base_info, tpl) == "张三"
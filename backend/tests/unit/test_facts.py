"""单元测试：事实卡 FactDatabase（coaching/facts）。

不依赖外部服务，验证 add/get/merge/remove/by_seg_id/as_text。
"""
from __future__ import annotations

from app.services.coaching.facts import FactDatabase


def test_facts_add_and_get():
    db = FactDatabase()
    db.add("客户", "某科技公司", "s1")
    f = db.get("客户")
    assert f and f.value == "某科技公司" and f.source == ["s1"]


def test_facts_same_key_merges():
    db = FactDatabase()
    db.add("客户", "某科技公司", "s1")
    db.add("客户", "某科技公司", "s2")
    assert db.get("客户").source == ["s1", "s2"]


def test_facts_remove():
    db = FactDatabase()
    db.add("客户", "某公司", "s1")
    db.remove("客户")
    assert db.get("客户") is None


def test_facts_by_seg_id():
    db = FactDatabase()
    db.add("客户", "某公司", "s1")
    db.add("预算", "10万", "s2")
    db.add("时间线", "3个月", "s1")
    facts = db.by_seg_id("s1")
    assert len(facts) == 2 and {f.key for f in facts} == {"客户", "时间线"}


def test_facts_as_text():
    db = FactDatabase()
    db.add("客户", "某科技公司", "s1")
    db.add("预算", "10万", "s2")
    text = db.as_text()
    assert "客户" in text and "某科技公司" in text and "s1" in text


def test_facts_as_text_empty():
    assert FactDatabase().as_text() == "（无事实卡）"

"""单元测试：LLM 输出契约校验（coaching/contract）。

不依赖外部服务，验证 validate_llm_item / validate_llm_output 的字段清洗与降级。
"""
from __future__ import annotations

from app.domain.coaching import ItemStatus
from app.services.coaching.contract import validate_llm_item, validate_llm_output


def test_contract_validate_ok():
    raw = {"id": "pain", "text": "团队经常漏需求", "status": "done",
           "reason": "用户明确说了", "covered_segments": ["s1", "s2"]}
    item = validate_llm_item(raw)
    assert item is not None and item.id == "pain" and item.status == ItemStatus.DONE
    assert item.covered_segments == ["s1", "s2"]


def test_contract_validate_null_id():
    item = validate_llm_item({"id": None, "text": "新冒出的问题", "status": "new"})
    assert item is not None and item.id is None


def test_contract_validate_whitespace_stripped():
    assert validate_llm_item({"id": "x", "text": "  前后有空格  ", "status": "todo"}).text == "前后有空格"


def test_contract_validate_empty_text_dropped():
    assert validate_llm_item({"id": "x", "text": "   ", "status": "todo"}) is None


def test_contract_validate_invalid_status_defaults_todo():
    assert validate_llm_item({"id": "x", "text": "hello", "status": "bad_status"}).status == ItemStatus.TODO


def test_contract_validate_non_dict():
    assert validate_llm_item("not a dict") is None and validate_llm_item(None) is None


def test_contract_output_list():
    assert len(validate_llm_output([
        {"id": "a", "text": "item a", "status": "done", "covered_segments": ["s1"]},
        {"id": None, "text": "item b", "status": "new"},
    ])) == 2


def test_contract_output_dict_items():
    assert len(validate_llm_output({"items": [{"id": "x", "text": "x item", "status": "todo"}]})) == 1


def test_contract_output_filters_bad():
    items = validate_llm_output([
        {"id": "good", "text": "good item", "status": "todo"},
        {"id": "bad", "text": "   ", "status": "todo"},
        {"text": "no id but ok", "status": "new"},
    ])
    assert len(items) == 2

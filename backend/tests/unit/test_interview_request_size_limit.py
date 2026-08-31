"""CreateInterviewRequest / UpdateInterviewRequest 的 base_info 字节上限校验。

防御：list / detail / export 接口把 base_info 全量塞返回，单条 5MB 字段会拖垮
整页列表。校验按 UTF-8 字节计，单字段 ≤ 4KB / 整体 ≤ 64KB（参考 issue #167）。
"""
from __future__ import annotations

import pytest

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.transport.http.schemas import (
    BASE_INFO_TOTAL_MAX_BYTES,
    BASE_INFO_VALUE_MAX_BYTES,
    CreateInterviewRequest,
    UpdateInterviewRequest,
)


def test_create_base_info_within_limits_ok():
    """合法 base_info（每字段 1KB、整体 5KB）→ 不抛。"""
    CreateInterviewRequest(
        template_id="cs-revisit",
        base_info={
            "title": "A" * 1024,
            "interviewee": "B" * 1024,
            "department": "C" * 1024,
            "topic": "D" * 1024,
            "note": "E" * 1024,
        },
        goal="quick check",
    )


def test_create_base_info_single_field_too_long_raises():
    """单字段 5KB → I18nError(VALUE_TOO_LONG, 422)。"""
    huge = "x" * 5000
    with pytest.raises(I18nError) as ei:
        CreateInterviewRequest(
            template_id="cs-revisit",
            base_info={"title": huge},
        )
    assert ei.value.code == Keys.SESSION_BASE_INFO_VALUE_TOO_LONG
    assert ei.value.http_status == 422
    assert ei.value.params["key"] == "title"
    assert ei.value.params["byte_len"] == 5002  # JSON 序列化后多 2 字节引号
    assert ei.value.params["max_bytes"] == BASE_INFO_VALUE_MAX_BYTES


def test_update_base_info_single_field_too_long_raises():
    """Update 路径同样校验（admin PATCH 是真实被利用入口）。"""
    huge = "y" * (BASE_INFO_VALUE_MAX_BYTES + 1)
    with pytest.raises(I18nError) as ei:
        UpdateInterviewRequest(base_info={"memo": huge})
    assert ei.value.code == Keys.SESSION_BASE_INFO_VALUE_TOO_LONG
    assert ei.value.params["key"] == "memo"


def test_update_base_info_none_skips_check():
    """Update 不传 base_info（仅改 goal）→ 跳过校验，不抛。"""
    UpdateInterviewRequest(goal="refocus")


def test_create_base_info_total_too_large_raises():
    """整体超 BASE_INFO_TOTAL_MAX_BYTES 抛 TOTAL_TOO_LARGE（每字段单独看都没超）。"""
    # 每字段 100 字节（远低于 4KB 单字段限）；700 字段 × 100 字节 ≈ 70KB > 64KB 总限
    too_many = {f"k{i}": "a" * 100 for i in range(700)}
    with pytest.raises(I18nError) as ei:
        CreateInterviewRequest(
            template_id="cs-revisit",
            base_info=too_many,
        )
    assert ei.value.code == Keys.SESSION_BASE_INFO_TOTAL_TOO_LARGE
    assert ei.value.http_status == 422
    assert ei.value.params["byte_len"] > BASE_INFO_TOTAL_MAX_BYTES


def test_create_base_info_non_string_value_counted_by_json():
    """list / dict 嵌套值走 json.dumps 序列化后再算字节——避免 4-byte emoji 撑爆字段。"""
    emoji_value = "🔥" * 1025  # 1025 × 4 字节 = 4100 > 4096
    with pytest.raises(I18nError) as ei:
        CreateInterviewRequest(
            template_id="cs-revisit",
            base_info={"note": emoji_value},
        )
    assert ei.value.code == Keys.SESSION_BASE_INFO_VALUE_TOO_LONG


def test_update_base_info_nested_dict_aggregated_into_total():
    """嵌套 dict 序列化字节数合并到 total——单字段不超限，但整体超。"""
    # 每个 nested 自身约 2.5KB（< 4KB 单字段限），放 30 个 → ~75KB > 64KB 总限
    payload = {f"k{i}": "x" * 100 for i in range(25)}  # ≈ 2500 字节序列化
    with pytest.raises(I18nError) as ei:
        UpdateInterviewRequest(base_info={f"slot{i}": payload for i in range(30)})
    assert ei.value.code == Keys.SESSION_BASE_INFO_TOTAL_TOO_LARGE
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
    _validate_base_info_size,
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
    """单字段 5KB → I18nError(VALUE_TOO_LONG, 422)。

    字节数 = key 字节 (5, "title") + json.dumps(value) 字节 (5002 = 5000 + 2 引号)
          = 5007。
    """
    huge = "x" * 5000
    with pytest.raises(I18nError) as ei:
        CreateInterviewRequest(
            template_id="cs-revisit",
            base_info={"title": huge},
        )
    assert ei.value.code == Keys.SESSION_BASE_INFO_VALUE_TOO_LONG
    assert ei.value.http_status == 422
    assert ei.value.params["field"] == "title"
    assert ei.value.params["byte_len"] == 5007  # 5 (key) + 5002 (json.dumps)
    assert ei.value.params["max_bytes"] == BASE_INFO_VALUE_MAX_BYTES


def test_update_base_info_single_field_too_long_raises():
    """Update 路径同样校验（admin PATCH 是真实被利用入口）。"""
    huge = "y" * (BASE_INFO_VALUE_MAX_BYTES + 1)
    with pytest.raises(I18nError) as ei:
        UpdateInterviewRequest(base_info={"memo": huge})
    assert ei.value.code == Keys.SESSION_BASE_INFO_VALUE_TOO_LONG
    assert ei.value.params["field"] == "memo"
    # key "memo" = 4 bytes；json.dumps(value) = 4097 + 2 引号 = 4099 → 4103
    assert ei.value.params["byte_len"] == 4103


def test_update_base_info_none_skips_check():
    """Update 不传 base_info（仅改 goal）→ 跳过校验，不抛。"""
    UpdateInterviewRequest(goal="refocus")


def test_create_base_info_total_too_large_raises():
    """整体超 BASE_INFO_TOTAL_MAX_BYTES 抛 TOTAL_TOO_LARGE（每字段单独看都没超）。

    整体按 json.dumps(base_info) 字节计（含 key + 结构开销），不再用累加单字段。
    """
    # 每字段 100 字节（远低于 4KB 单字段限）；700 字段 × ~110 字节 ≈ 77KB > 64KB 总限
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
    # 每个 nested 自身约 2.5KB（< 4KB 单字段限），放 30 个 → ~82KB > 64KB 总限
    payload = {f"k{i}": "x" * 100 for i in range(25)}  # ≈ 2750 字节序列化
    with pytest.raises(I18nError) as ei:
        UpdateInterviewRequest(base_info={f"slot{i}": payload for i in range(30)})
    assert ei.value.code == Keys.SESSION_BASE_INFO_TOTAL_TOO_LARGE


def test_create_base_info_long_key_short_value_blocked_by_per_field():
    """长 key + 极短 value 仍被单字段上限挡住——key 字节不能漏算。

    攻击示例：10000 个 10000 字节的 key + 单字节 value (0)，每个 value=1B OK，
    但实际 JSON 含 key 字节 ≈ 100MB，远超单字段 / 整体上限。
    """
    huge_key = "k" * (BASE_INFO_VALUE_MAX_BYTES + 1)  # 4097 字节 key
    with pytest.raises(I18nError) as ei:
        CreateInterviewRequest(
            template_id="cs-revisit",
            base_info={huge_key: 0},  # value=0 经 json.dumps = 1 字节
        )
    assert ei.value.code == Keys.SESSION_BASE_INFO_VALUE_TOO_LONG
    assert ei.value.params["field"] == huge_key


def test_create_base_info_non_json_native_value_serialized_via_str():
    """datetime / Decimal 等非 JSON 原生类型走 default=str 兜底，转 422 而非 500。"""
    from datetime import datetime
    from decimal import Decimal

    # 短 datetime / Decimal 应能序列化（不抛 TypeError），整体校验通过
    CreateInterviewRequest(
        template_id="cs-revisit",
        base_info={"when": datetime(2099, 1, 1)},
    )
    CreateInterviewRequest(
        template_id="cs-revisit",
        base_info={"price": Decimal("99.99")},
    )


# ---- 合并上限（PATCH 增量路径，#167 放大器攻击面）----

def test_validate_merged_base_info_total_too_large_raises():
    """PATCH 合并路径：merged 整体超 64KB 必须被 _validate_base_info_size 拒。

    场景：先 POST 60KB base_info（schema 整体校验通过），再 PATCH 一段 10KB 增量
    （单次校验只看 10KB 也通过）——manager.update 用 {**existing, **req} 合并落库，
    若无 merged 兜底校验，DB 里就成了 70KB，绕过整体上限。route 层在 manager.update
    之前对 merged 跑 _validate_base_info_size，必须拦截。

    这里直接验证 _validate_base_info_size 的契约（route 行为等价的最小单元）。
    """
    # 已有 ~30KB base_info；PATCH 一个 ~35KB 增量 → 合并后 ~65KB > 64KB
    existing_base = {f"existing_{i}": "x" * 100 for i in range(300)}
    new_patch = {f"new_{i}": "y" * 100 for i in range(300)}
    merged = {**existing_base, **new_patch}
    with pytest.raises(I18nError) as ei:
        _validate_base_info_size(merged)
    assert ei.value.code == Keys.SESSION_BASE_INFO_TOTAL_TOO_LARGE
    assert ei.value.http_status == 422
    assert ei.value.params["byte_len"] > BASE_INFO_TOTAL_MAX_BYTES


def test_validate_merged_base_info_within_limits_ok():
    """PATCH 合并后仍在 64KB 内 → 不抛。"""
    existing_base = {f"e{i}": "x" * 100 for i in range(100)}  # ~11KB
    new_patch = {f"n{i}": "y" * 100 for i in range(100)}  # ~11KB 增量
    merged = {**existing_base, **new_patch}  # ~22KB < 64KB
    _validate_base_info_size(merged)  # 不抛即通过

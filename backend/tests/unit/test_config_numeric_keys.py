"""NUMERIC_KEYS 校验：写入校验兜住 0 / 非数 / NaN / Infinity。

回归 issue #123：原 `validate_value` 数值分支保留裸 ValueError，admin PUT
/api/v1/admin/config/auth 把 jwt_expire_minutes 改成 "0" / "nan" / "inf"
时路由层没翻译，FastAPI 直接返 500 + "Internal Server Error"。修复后
应与 BOOL_KEYS / ENUM_KEYS 走 I18nError(http_status=400) 同一形态。

数值 key 按 typ 拆 config.invalid_positive_integer /
config.invalid_positive_number 两个 key（避免共占位符硬塞英文字面量）；
浮点 NaN / Infinity / 科学记数法溢出走 math.isfinite(v) 兜住。
"""
from __future__ import annotations

import pytest

from app.core.config_store import NUMERIC_KEYS, validate_value
from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys


def test_numeric_keys_exact_set():
    """NUMERIC_KEYS 必须是这组 key；新增数值字段必须同步更新本断言。"""
    assert set(NUMERIC_KEYS.keys()) == {
        "asr.funasr_server.sample_rate",
        "asr.doubao_stream.sample_rate",
        "coach.max_pending_segments",
        "auth.jwt_expire_minutes",
        "auth.refresh_token_expire_days",
        "session.max_concurrent",
        "coach.pause_s",
        "coach.min_interval_s",
        "coach.llm_timeout_s",
        "session.grace_period_s",
        "session.idle_timeout_s",
        "session.idle_check_interval_s",
        "session.liveness_window_s",
    }


def test_numeric_keys_int_keys_are_int():
    """int 字段必须用 int 类型校验——若误填 float，会拒绝 "60.0" 这类合法 str。"""
    int_keys = {k for k, t in NUMERIC_KEYS.items() if t is int}
    assert "auth.jwt_expire_minutes" in int_keys
    assert "coach.pause_s" not in int_keys


def test_numeric_keys_float_keys_are_float():
    float_keys = {k for k, t in NUMERIC_KEYS.items() if t is float}
    assert "coach.pause_s" in float_keys
    assert "auth.jwt_expire_minutes" not in float_keys


def test_validate_value_accepts_jwt_expire_minutes_60():
    validate_value("auth.jwt_expire_minutes", "60")  # 不抛


def test_validate_value_accepts_coach_pause_s():
    validate_value("coach.pause_s", "5.0")  # 不抛


def test_validate_value_rejects_jwt_expire_zero_with_i18n():
    """'0' 必须被拒，且走 I18nError 而非裸 ValueError——前者会被路由层翻译。"""
    with pytest.raises(I18nError) as ei:
        validate_value("auth.jwt_expire_minutes", "0")
    assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_INTEGER.value
    assert ei.value.params["name"] == "auth.jwt_expire_minutes"
    assert ei.value.params["value"] == "0"
    assert ei.value.http_status == 400


def test_validate_value_rejects_jwt_expire_negative_with_i18n():
    with pytest.raises(I18nError) as ei:
        validate_value("auth.jwt_expire_minutes", "-3")
    assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_INTEGER.value
    assert ei.value.http_status == 400


def test_validate_value_rejects_jwt_expire_nan_with_i18n():
    """int('nan') 抛 ValueError，必须被 I18nError 兜住。"""
    with pytest.raises(I18nError) as ei:
        validate_value("auth.jwt_expire_minutes", "nan")
    assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_INTEGER.value
    assert ei.value.http_status == 400


def test_validate_value_rejects_jwt_expire_inf_with_i18n():
    with pytest.raises(I18nError) as ei:
        validate_value("auth.jwt_expire_minutes", "inf")
    assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_INTEGER.value
    assert ei.value.http_status == 400


def test_validate_value_rejects_float_nan_with_i18n():
    """float('nan') 会绕过 `v <= 0`（NaN <= 0 永远 False）直接落库，必须前置拦截。"""
    with pytest.raises(I18nError) as ei:
        validate_value("coach.pause_s", "nan")
    assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_NUMBER.value
    assert ei.value.http_status == 400


def test_validate_value_rejects_float_inf_with_i18n():
    with pytest.raises(I18nError) as ei:
        validate_value("coach.pause_s", "inf")
    assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_NUMBER.value
    assert ei.value.http_status == 400


def test_validate_value_rejects_float_negative_inf_with_i18n():
    with pytest.raises(I18nError) as ei:
        validate_value("coach.pause_s", "-infinity")
    assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_NUMBER.value
    assert ei.value.http_status == 400


def test_validate_value_rejects_float_signed_nan_inf_with_i18n():
    """'+nan' / '+inf' / 科学记数法溢出：字符串预检漏掉，math.isfinite 兜住。"""
    for bad in ("+nan", "+inf", "+infinity", "1e10000"):
        with pytest.raises(I18nError) as ei:
            validate_value("coach.pause_s", bad)
        assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_NUMBER.value
        assert ei.value.http_status == 400


def test_validate_value_rejects_non_numeric_with_i18n():
    """'abc' 既不是数字也不是 enum/bool——数值分支抛 I18nError 而非裸 ValueError。"""
    with pytest.raises(I18nError) as ei:
        validate_value("auth.jwt_expire_minutes", "abc")
    assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_INTEGER.value
    assert ei.value.http_status == 400


def test_validate_value_accepts_float_string_for_float_key():
    """float 字段接受 '5.5' 这种合法值。"""
    validate_value("coach.pause_s", "5.5")  # 不抛


def test_validate_value_rejects_float_string_for_int_key():
    """int 字段拒绝 '5.5'——int('5.5') 抛 ValueError，被 I18nError 兜住。"""
    with pytest.raises(I18nError) as ei:
        validate_value("auth.jwt_expire_minutes", "5.5")
    assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_INTEGER.value
    assert ei.value.http_status == 400


@pytest.mark.parametrize(
    "key,code",
    [
        ("auth.jwt_expire_minutes", Keys.CONFIG_INVALID_POSITIVE_INTEGER.value),
        ("coach.pause_s", Keys.CONFIG_INVALID_POSITIVE_NUMBER.value),
    ],
)
def test_i18n_positive_message_translates_in_each_locale(key, code):
    """4 个 locale 都已注册 int / float 两个 key；非英语 locale 必须给出本地化文本
    （含 locale 母语字符），不能再夹英文字面量占位符（修复前 'positive integer'
    字面量塞进 zh-CN / vi-VN 文案不可读）。
    """
    from app.core.i18n.translator import t

    # 期望每个 locale 给出的关键本地化短语（int / float 两种 key 各对应一组）
    expectations = {
        ("zh-CN", Keys.CONFIG_INVALID_POSITIVE_INTEGER.value): "正整数",
        ("zh-TW", Keys.CONFIG_INVALID_POSITIVE_INTEGER.value): "正整數",
        ("en-US", Keys.CONFIG_INVALID_POSITIVE_INTEGER.value): "positive integer",
        ("vi-VN", Keys.CONFIG_INVALID_POSITIVE_INTEGER.value): "số nguyên dương",
        ("zh-CN", Keys.CONFIG_INVALID_POSITIVE_NUMBER.value): "正数",
        ("zh-TW", Keys.CONFIG_INVALID_POSITIVE_NUMBER.value): "正數",
        ("en-US", Keys.CONFIG_INVALID_POSITIVE_NUMBER.value): "positive number",
        ("vi-VN", Keys.CONFIG_INVALID_POSITIVE_NUMBER.value): "số dương",
    }
    for locale in ("zh-CN", "zh-TW", "en-US", "vi-VN"):
        msg = t(
            code,
            locale=locale,
            name=key,
            value="0",
        )
        assert msg, f"{locale}/{code} 应返回非空译文"
        assert key in msg, f"{locale}/{code} 译文应含 key 名 '{key}'，实际: {msg!r}"
        assert expectations[(locale, code)] in msg, (
            f"{locale}/{code} 译文应含本地化短语 {expectations[(locale, code)]!r}，"
            f"实际: {msg!r}"
        )

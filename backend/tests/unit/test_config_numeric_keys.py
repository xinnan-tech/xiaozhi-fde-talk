"""NUMERIC_KEYS 校验：写入校验兜住 0 / 非数 / NaN / Infinity / 上限超界。

回归 issue #123：原 `validate_value` 数值分支保留裸 ValueError，admin PUT
/api/v1/admin/config/auth 把 jwt_expire_minutes 改成 "0" / "nan" / "inf"
时路由层没翻译，FastAPI 直接返 500 + "Internal Server Error"。修复后
应与 BOOL_KEYS / ENUM_KEYS 走 I18nError(http_status=400) 同一形态。

数值 key 按 typ 拆 config.invalid_positive_integer /
config.invalid_positive_number 两个 key（避免共占位符硬塞英文字面量）；
浮点 NaN / Infinity / 科学记数法溢出走 math.isfinite(v) 兜住。

回归 issue #201：补 NUMERIC_MAX_VALUE 上限校验。
"""
from __future__ import annotations

import pytest

from app.core.config_store import NUMERIC_KEYS, NUMERIC_MAX_VALUE, validate_value
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


# ---- #201 上限校验 ----
# NUMERIC_MAX_VALUE 限定的 key 必须有上限；扩展 NUMERIC_KEYS 中其他 key 时如
# 需上限再加进本表。

def test_numeric_max_value_keys_are_subset_of_numeric_keys():
    """NUMERIC_MAX_VALUE 不能含 NUMERIC_KEYS 之外的 key——这些 key 没走数值校验。"""
    extra = set(NUMERIC_MAX_VALUE) - set(NUMERIC_KEYS)
    assert not extra, f"NUMERIC_MAX_VALUE 列出非数值 key: {extra}"


def test_numeric_max_value_exact_set():
    """新增/调整上限必须同步更新本断言。"""
    assert set(NUMERIC_MAX_VALUE.keys()) == {
        "auth.jwt_expire_minutes",
        "auth.refresh_token_expire_days",
        "session.max_concurrent",
        "coach.max_pending_segments",
        "asr.funasr_server.sample_rate",
        "asr.doubao_stream.sample_rate",
    }


def test_numeric_max_value_jwt_expire_is_30_days():
    """jwt_expire_minutes 上限 30 天 = 43200 分钟（issue 提议值，与 refresh 默认对齐）。"""
    assert NUMERIC_MAX_VALUE["auth.jwt_expire_minutes"] == 30 * 24 * 60


def test_numeric_max_value_sample_rate_is_192khz():
    """sample_rate 上限 192000（专业音频最大标准采样率），挡住 #201 同根因的
    OOM 分配（funasr_server.py:215 / doubao_stream.py:187 的 silence_bytes 公式）。
    """
    assert NUMERIC_MAX_VALUE["asr.funasr_server.sample_rate"] == 192000
    assert NUMERIC_MAX_VALUE["asr.doubao_stream.sample_rate"] == 192000


def test_validate_value_rejects_sample_rate_oom():
    """#201 同根因：funasr_server/doubao_stream 的 silence_bytes 分配
    (sample_rate * 2 * tail_ms // 1000) 一次性按比例放大，999999999 直接 OOM。
    """
    for key in ("asr.funasr_server.sample_rate", "asr.doubao_stream.sample_rate"):
        with pytest.raises(I18nError) as ei:
            validate_value(key, "999999999")
        assert ei.value.code == Keys.CONFIG_INVALID_NUMERIC_TOO_LARGE.value
        assert ei.value.params["max"] == 192000


def test_validate_value_accepts_sample_rate_at_max():
    """192000 边界值必须接受。"""
    for key in ("asr.funasr_server.sample_rate", "asr.doubao_stream.sample_rate"):
        validate_value(key, "192000")


def test_validate_value_rejects_max_pending_segments_unbounded():
    """#201 同根因：engine.py:277 用 max_pending_segments 作 segment buffer
    阈值判定，无上限会让兜底永远不命中、退化为无界 buffer。
    """
    with pytest.raises(I18nError) as ei:
        validate_value("coach.max_pending_segments", "999999999")
    assert ei.value.code == Keys.CONFIG_INVALID_NUMERIC_TOO_LARGE.value
    assert ei.value.params["max"] == 1000


def test_validate_value_accepts_max_pending_segments_default():
    """DEFAULTS coach.max_pending_segments=8 须在 1000 上限内。"""
    validate_value("coach.max_pending_segments", "8")


def test_validate_value_rejects_jwt_expire_overflow_99999999999():
    """#201 触发条件：9 个 9 的 minutes → token.py datetime+timedelta OverflowError。
    必须在写入层挡下，admin 收到 400 + 结构化 code 而非 500。
    """
    with pytest.raises(I18nError) as ei:
        validate_value("auth.jwt_expire_minutes", "99999999999")
    assert ei.value.code == Keys.CONFIG_INVALID_NUMERIC_TOO_LARGE.value
    assert ei.value.http_status == 400
    assert ei.value.params["name"] == "auth.jwt_expire_minutes"
    assert ei.value.params["value"] == "99999999999"
    assert ei.value.params["max"] == NUMERIC_MAX_VALUE["auth.jwt_expire_minutes"]


def test_validate_value_rejects_jwt_expire_above_max():
    """43201 minutes（30 天 + 1）必须拒；43200 必须收（边界闭）。"""
    with pytest.raises(I18nError) as ei:
        validate_value("auth.jwt_expire_minutes", "43201")
    assert ei.value.code == Keys.CONFIG_INVALID_NUMERIC_TOO_LARGE.value


def test_validate_value_accepts_jwt_expire_at_max():
    """43200 minutes（=30 天）= 上限，必须接受（边界闭）。"""
    validate_value("auth.jwt_expire_minutes", str(NUMERIC_MAX_VALUE["auth.jwt_expire_minutes"]))


def test_validate_value_accepts_jwt_expire_default():
    """DEFAULTS 中 jwt_expire_minutes=10080（7 天）须在上限内——避免坏 DEFAULTS 触发
    warm() fail-fast 而非「配置 bug 必现」级误报。
    """
    validate_value("auth.jwt_expire_minutes", "10080")


def test_validate_value_rejects_refresh_token_days_overflow():
    """#201：refresh_token_expire_days=99999 → token.py 同样 OverflowError。"""
    with pytest.raises(I18nError) as ei:
        validate_value("auth.refresh_token_expire_days", "99999")
    assert ei.value.code == Keys.CONFIG_INVALID_NUMERIC_TOO_LARGE.value
    assert ei.value.http_status == 400
    assert ei.value.params["name"] == "auth.refresh_token_expire_days"
    assert ei.value.params["max"] == 365


def test_validate_value_accepts_refresh_token_days_default():
    """DEFAULTS refresh_token_expire_days=30 须在 365 上限内。"""
    validate_value("auth.refresh_token_expire_days", "30")


def test_validate_value_rejects_max_concurrent_absurd():
    """#201：session.max_concurrent=999999 接受但无意义——会掩盖真实限流失效。"""
    with pytest.raises(I18nError) as ei:
        validate_value("session.max_concurrent", "999999")
    assert ei.value.code == Keys.CONFIG_INVALID_NUMERIC_TOO_LARGE.value
    assert ei.value.http_status == 400
    assert ei.value.params["name"] == "session.max_concurrent"
    assert ei.value.params["max"] == 1000


def test_validate_value_accepts_max_concurrent_default():
    """DEFAULTS session.max_concurrent=10 须在 1000 上限内。"""
    validate_value("session.max_concurrent", "10")


def test_validate_value_max_check_does_not_apply_to_other_numeric_keys():
    """NUMERIC_MAX_VALUE 没列出的数值 key（如 coach.pause_s）无上限——大数被允许
    （只要合法）。验证方式：传一个大于 jwt 上限的合法 float 不应拒。
    """
    # 1e9 秒 ≈ 31 年；超过 jwt 上限但 coach.pause_s 不受 NUMERIC_MAX_VALUE 限制。
    validate_value("coach.pause_s", "1000000000.0")  # 不抛


def test_validate_value_max_rejection_takes_precedence_over_positive():
    """max 校验在 <= 0 之后——负数仍走 positive_integer 而非 too_large（更具体的错误优先）。"""
    with pytest.raises(I18nError) as ei:
        validate_value("auth.jwt_expire_minutes", "-1")
    assert ei.value.code == Keys.CONFIG_INVALID_POSITIVE_INTEGER.value


def test_i18n_too_large_message_translates_in_each_locale():
    """4 个 locale 都必须本地化 config.invalid_numeric_too_large 的 {name}/{max}/{value} 占位符。"""
    from app.core.i18n.translator import t

    code = Keys.CONFIG_INVALID_NUMERIC_TOO_LARGE.value
    expectations = {
        "zh-CN": "不能超过",
        "zh-TW": "不能超過",
        "en-US": "cannot exceed",
        "vi-VN": "không được vượt quá",
    }
    for locale in ("zh-CN", "zh-TW", "en-US", "vi-VN"):
        msg = t(
            code,
            locale=locale,
            name="auth.jwt_expire_minutes",
            value="99999999999",
            max=43200,
        )
        assert msg, f"{locale}/{code} 应返回非空译文"
        assert "auth.jwt_expire_minutes" in msg, f"{locale} 译文应含 key 名，实际: {msg!r}"
        assert "99999999999" in msg, f"{locale} 译文应含 value，实际: {msg!r}"
        assert "43200" in msg, f"{locale} 译文应含 max=43200，实际: {msg!r}"
        assert expectations[locale] in msg, (
            f"{locale} 译文应含本地化短语 {expectations[locale]!r}，实际: {msg!r}"
        )

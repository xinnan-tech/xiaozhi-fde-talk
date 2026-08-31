"""模板校验错误 i18n：每条具体原因在 4 个 locale 下都能翻译，detail 非空且不含中文残留。

回归 issue #121：原实现把 `reason` 字段硬编码中文塞进 I18nError 模板，
英文 / 越南文 admin 弹窗混杂中文。修复后 10 个具体原因都有独立 i18n key，
每个 locale 都翻译到位。
"""
from __future__ import annotations

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.core.i18n.translator import t

# 10 个具体 key——加新条目时务必同步到这里
SPECIFIC_KEYS = [
    Keys.TEMPLATE_INVALID_ID_FORMAT,
    Keys.TEMPLATE_INVALID_VERSION_FORMAT,
    Keys.TEMPLATE_INVALID_VERSION_TOO_SMALL,
    Keys.TEMPLATE_INVALID_VERSION_OVERFLOW,
    Keys.TEMPLATE_INVALID_DUPLICATE_FIELD,
    Keys.TEMPLATE_INVALID_DUPLICATE_MUST_ASK_ID,
    Keys.TEMPLATE_INVALID_MISSING_REF,
    Keys.TEMPLATE_INVALID_ID_MISMATCH,
    Keys.TEMPLATE_INVALID_BRIEF_EMPTY,
    Keys.TEMPLATE_INVALID_BRIEF_TOO_LONG,
]


def _sample_params(key: Keys) -> dict:
    """每个 key 给一组能填满占位符的最小参数。"""
    if key == Keys.TEMPLATE_INVALID_ID_FORMAT:
        return {"id": "Bad_Id!"}
    if key in (
        Keys.TEMPLATE_INVALID_VERSION_FORMAT,
        Keys.TEMPLATE_INVALID_VERSION_TOO_SMALL,
        Keys.TEMPLATE_INVALID_VERSION_OVERFLOW,
    ):
        return {"version": "abc"}
    if key == Keys.TEMPLATE_INVALID_BRIEF_TOO_LONG:
        return {"max_chars": 2000}
    if key == Keys.TEMPLATE_INVALID_DUPLICATE_FIELD:
        return {"keys": ["project", "customer"]}
    if key == Keys.TEMPLATE_INVALID_DUPLICATE_MUST_ASK_ID:
        return {"ids": ["q1", "q2"]}
    if key == Keys.TEMPLATE_INVALID_MISSING_REF:
        return {"attr": "extract_to", "missing": ["nope"]}
    if key == Keys.TEMPLATE_INVALID_ID_MISMATCH:
        return {"path": "x", "body": "y"}
    return {}


def test_all_specific_keys_translate_in_4_locales():
    """4 个 locale 都必须注册每个具体 key，且翻译后非空。"""
    for locale in ("zh-CN", "zh-TW", "en-US", "vi-VN"):
        for key in SPECIFIC_KEYS:
            params = _sample_params(key)
            err = I18nError(key.value, http_status=422, **params)
            msg = err.localized(locale)
            assert msg, f"{locale}: {key.value} 翻译为空"
            # 非中文 locale 不应出现中文字符
            if locale in ("en-US", "vi-VN"):
                # 简易检查——任意 CJK 都视为残留
                assert not any("一" <= ch <= "鿿" for ch in msg), (
                    f"{locale}: {key.value} 残留中文：{msg}"
                )


def test_i18n_error_localizes_at_transport_layer():
    """I18nError 在 transport 层翻译——params 透传、code 不变。"""
    err = I18nError(
        Keys.TEMPLATE_INVALID_MISSING_REF.value,
        http_status=422, attr="extract_to", missing="nope",
    )
    assert err.http_status == 422
    assert err.params == {"attr": "extract_to", "missing": "nope"}
    msg_en = err.localized("en-US")
    msg_zh = err.localized("zh-CN")
    # 英文版必须含 extract_to/nope
    assert "extract_to" in msg_en
    assert "nope" in msg_en
    # 中文版必须含相关字段名
    assert "extract_to" in msg_zh


def test_en_locale_uses_template_invalid_prefixed_codes():
    """回归 en-US / vi-VN 下 detail 不混杂中文——直接调 t() 验。"""
    msg_en = t(
        Keys.TEMPLATE_INVALID_DUPLICATE_FIELD.value, locale="en-US",
        keys="project",
    )
    msg_vi = t(
        Keys.TEMPLATE_INVALID_DUPLICATE_FIELD.value, locale="vi-VN",
        keys="project",
    )
    assert "project" in msg_en
    assert "project" in msg_vi
    for msg in (msg_en, msg_vi):
        assert not any("一" <= ch <= "鿿" for ch in msg), msg

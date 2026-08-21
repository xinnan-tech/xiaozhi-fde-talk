"""报告 prompt：zh_tw 必须显式切繁体——base 整体英文后通过 lang_native 注入「繁體中文」。

Stage 2 后所有语种共用同一段 _REPORT_SYSTEM，差异仅在 format 占位符值。
"""
from app.services.reports.generator import _FALLBACK_BY_LANG, _report_system


def test_zh_tw_system_injects_traditional_chinese_label():
    """zh_tw system 必须含「繁體中文」字样——LLM 据此输出繁中。"""
    body = _report_system("zh_tw")
    assert "繁體中文" in body, f"zh_tw system 未注入繁體中文：{body[:300]!r}"


def test_zh_tw_system_uses_traditional_fallback_phrase():
    """zh_tw system 必须含 _FALLBACK_BY_LANG["zh_tw"] 短语——与后处理兜底一致。"""
    body = _report_system("zh_tw")
    assert _FALLBACK_BY_LANG["zh_tw"] in body, (
        f"zh_tw system 未内嵌兜底短语 {_FALLBACK_BY_LANG['zh_tw']!r}"
    )


def test_zh_tw_output_language_section_present():
    """zh_tw system 含 `## Output language (繁體中文, mandatory)`——正面声明输出语种。"""
    body = _report_system("zh_tw")
    assert "## Output language (繁體中文, mandatory)" in body, (
        f"zh_tw system 缺输出语种正面声明：{body[:300]!r}"
    )
"""报告指令：zh_tw 不再为空，必须显式切繁体。"""
from app.services.reports.generator import _REPORT_LANG_INSTRUCTION, _report_system


def test_zh_tw_instruction_is_non_empty():
    assert _REPORT_LANG_INSTRUCTION["zh_tw"], "zh_tw 报告指令不应为空——否则仍会输出简体"


def test_zh_tw_instruction_mentions_traditional_chinese():
    body = _report_system("zh_tw").lower()
    assert "繁體" in body or "繁体" in body, f"zh_tw 指令未提及繁体中文：{body!r}"


def test_zh_cn_keeps_no_extra_instruction():
    """默认 zh_cn：base prompt + 空字符串 = 与改前一致，不回归。"""
    base = _report_system("en")  # en 有显式指令
    cn = _report_system("zh_cn")
    # zh_cn 应该比 en 短（少了 "Output language" 段落）
    assert len(cn) < len(base)

"""报告 prompt：英文指令必须足以对抗 qwen-plus 的「中文 base」语种倾向。

回归需求：把 _REPORT_LANG_INSTRUCTION["en"] 的强约束断言下来，防止弱化。
"""
from app.services.reports.generator import _REPORT_LANG_INSTRUCTION, _report_system


def test_en_directive_is_non_empty():
    assert _REPORT_LANG_INSTRUCTION["en"], "en 指令不应为空——否则仍是中文基线"


def test_en_directive_demands_full_english():
    body = _report_system("en").lower()
    assert "entire" in body, f"en 指令未约束 ENTIRE（应强制全文英文）：{body!r}"
    assert "synthesize" in body or "synthesis" in body, (
        f"en 指令未要求把中文转写合成英文：{body!r}"
    )


def test_en_directive_provides_fallback_phrase():
    body = _report_system("en")
    assert "Not mentioned in this interview." in body, (
        f"en 指令未定义「未提及」兜底短语（防止后处理注入中文）：{body!r}"
    )


def test_en_directive_tells_llm_to_ignore_chinese_base():
    body = _report_system("en").lower()
    assert "ignore" in body and "chinese" in body and "structural" in body, (
        f"en 指令未显式让 LLM 忽略 base prompt 的中文结构约束（qwen-plus 的镜像行为突破口）：{body!r}"
    )


def test_en_directive_preserves_placeholder_and_skill_rules():
    """占位符与 skill 标记规则对所有语种通用，en 必须包含。"""
    body = _report_system("en")
    assert "{{session.X}}" in body or "session.X" in body, (
        f"en 指令未保留 session 占位规则：{body!r}"
    )
    assert "skill:" in body, f"en 指令未保留 skill 标记规则：{body!r}"


def test_zh_cn_directive_unchanged():
    """zh_cn 仍走中文 base，directive 不追加。防保护性失效。"""
    assert _REPORT_LANG_INSTRUCTION["zh_cn"] == "", (
        f"zh_cn 不应追加 directive（会破坏中文报告形态）：{_REPORT_LANG_INSTRUCTION['zh_cn']!r}"
    )


def test_en_longer_than_zh_cn():
    """en 必须比 zh_cn 长（强约束必然比空 directive 长）。"""
    en = _report_system("en")
    cn = _report_system("zh_cn")
    assert len(en) > len(cn), (
        f"en ({len(en)}) 应比 zh_cn ({len(cn)}) 长——directive 必须有内容"
    )

"""报告悬空标签兜底按语种切：英文报告不会被注入「本次访谈未提及」。
"""
from app.services.reports.generator import _fill_dangling_labels


def test_fills_label_with_zh_cn_fallback():
    md = "## Section\n- 机会点 / 优先级建议：\n- 待验证假设：\n\n## Next"
    out = _fill_dangling_labels(md, language="zh_cn")
    assert "- 机会点 / 优先级建议： 本次访谈未提及" in out
    assert "- 待验证假设： 本次访谈未提及" in out


def test_fills_label_with_zh_tw_fallback():
    md = "- 機會點 / 優先級建議：\n- 待驗證假設："
    out = _fill_dangling_labels(md, language="zh_tw")
    assert "- 機會點 / 優先級建議： 本次訪談未提及" in out
    assert "- 待驗證假設： 本次訪談未提及" in out


def test_fills_label_with_en_fallback():
    md = "## Section\n- Opportunity / priority recommendation:\n- Hypothesis to verify:\n\n## Next"
    out = _fill_dangling_labels(md, language="en")
    assert "- Opportunity / priority recommendation: Not mentioned in this interview." in out
    assert "- Hypothesis to verify: Not mentioned in this interview." in out


def test_en_fallback_does_not_inject_chinese():
    """关键回归：英文报告不应被注入「本次访谈未提及」。"""
    md = "- Customer / industry:"
    out = _fill_dangling_labels(md, language="en")
    assert "本次访谈未提及" not in out
    assert "Not mentioned in this interview." in out


def test_keeps_inline_content():
    md = "- Pain: pre-sales records leak\n- Customer: Not mentioned in this interview."
    assert _fill_dangling_labels(md, language="en") == md


def test_keeps_sub_bullet_form():
    md = "- Pain:\n  - pre-sales leak\n  - scattered notes"
    assert _fill_dangling_labels(md, language="en") == md


def test_trailing_spaces_treated_as_empty():
    md = "- Opportunity:  \n- Next:"
    out = _fill_dangling_labels(md, language="en")
    assert out.count("Not mentioned in this interview.") == 2


def test_unknown_language_falls_back_to_en():
    """未知语种应回退到 en 短语（消除英文报告被注入中文的隐性 bug）。

    Stage 5：兜底回退从 zh_cn 改 en——与 get_lang_meta 未知 lang fallback 一致。
    """
    md = "- 机会点："
    out = _fill_dangling_labels(md, language="klingon")
    assert "- 机会点： Not mentioned in this interview." in out
    # 不再被注入中文短语
    assert "本次访谈未提及" not in out

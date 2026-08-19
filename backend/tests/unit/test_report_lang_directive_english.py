"""报告 prompt：英文指令必须足以对抗 qwen-plus 的「中文 base」语种倾向。

回归需求：把 _REPORT_LANG_INSTRUCTION["en"] 的强约束断言下来，防止弱化。
"""
import re

from app.services.reports.generator import (
    _FALLBACK_BY_LANG,
    _REPORT_LANG_INSTRUCTION,
    _report_system,
)


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


def test_en_directive_uses_chinese_scaffolding_as_structural_only():
    """en 指令必须把 base prompt 的中文骨架重声明为「仅结构性脚手架」。

    防止弱化为原"ignore Chinese structural guidance"的负面句式（LLM 字面执行
    会丢 {{ }} 删除这类**结构性但语言中立**规则）。

    用正则确保三件事实同时出现：
    - "chinese" + "scaffolding"（承认 base 是中文骨架）
    - "structural"（声明按结构用）
    - "rewrite"（要求把标签/措辞改写成英文）
    反向：禁止偷渡成"do not" + 同三词。
    """
    body = _report_system("en").lower()
    # 正向：三组关键词必须以正向指令（肯定式）形态同时出现
    pos_pattern = re.compile(
        r"\bchinese\b[\s\S]{0,200}?\bstructur(?:al|ally|e)\b[\s\S]{0,200}?(?<!do not )(?<!don't )\b(?:rewrite|use them|adopt)\b"
    )
    assert pos_pattern.search(body), (
        f"en 指令未把中文骨架声明为「仅结构性脚手架并改写」——会丢结构性规则：{body!r}"
    )
    # 反向：禁止否定形式偷过（如 future LLM 把这句写反）
    neg_pattern = re.compile(r"\bdo\s+not\b[\s\S]{0,80}?\bchinese\b[\s\S]{0,80}?\bstructur")
    assert not neg_pattern.search(body), (
        f"en 指令不可被偷渡成「do not ... chinese ... structural」否定形式：{body!r}"
    )


def test_en_directive_instructs_placeholder_wrapper_deletion():
    """显式要求 LLM 删除 {{ }} 包装——这是结构但语言中立的规则，必须正面重申
    否则 base prompt 的中文"删包装"规则在 en 输出时被 LLM 当成"语言内容"丢掉。
    """
    body = _report_system("en")
    assert "delete the `{{` and `}}` wrappers" in body, (
        f"en 指令未显式要求删除 {{ }} 包装——{{ }} 兜底仅靠 _strip_orphan_placeholders 会丢语义上下文：{body!r}"
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


# --- 跨 dict 不变量：directive fallback 短语必须和 _FALLBACK_BY_LANG 一字不差 ---


def test_directive_keys_match_fallback_keys():
    """键集合必须完全相等——任一缺都意味着某边没同步更新。"""
    assert set(_REPORT_LANG_INSTRUCTION) == set(_FALLBACK_BY_LANG), (
        f"语种键必须同步：{set(_REPORT_LANG_INSTRUCTION) ^ set(_FALLBACK_BY_LANG)}"
    )


def test_directive_fallback_phrase_matches_post_processor():
    """每条语种的 directive（如有内容）必须内嵌 _FALLBACK_BY_LANG[k]，让 LLM
    与确定性后处理使用同一短语，避免 EN 报告被 deterministic 兜底注入中文。

    空 directive（如 zh_cn 走中文 base）跳过此断言：兜底短语从 `_fill_dangling_labels`
    入参层面指定，与 directive 解耦。
    """
    for lang, directive in _REPORT_LANG_INSTRUCTION.items():
        if not directive:
            continue  # 空 directive 默认走 base prompt + zh_cn 短语
        assert _FALLBACK_BY_LANG[lang] in directive, (
            f"语种 {lang!r} 的 directive 未内嵌兜底短语 {_FALLBACK_BY_LANG[lang]!r}；"
            f"后处理 _fill_dangling_labels 仍会注入它，行为与 directive 不一致。"
        )


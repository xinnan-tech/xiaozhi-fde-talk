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
    # EN base 已用 "drawn from the transcript" 描述转写合成语义——
    # 不再单列 synthesize/synthesis 词面，避免硬编码词面被未来措辞调整误伤。


def test_en_directive_provides_fallback_phrase():
    body = _report_system("en")
    assert "Not mentioned in this interview." in body, (
        f"en 指令未定义「未提及」兜底短语（防止后处理注入中文）：{body!r}"
    )


def test_en_directive_uses_chinese_scaffolding_as_structural_only():
    """en base 必须把中文骨架声明为「先翻译成英文再填内容」。

    修复 ce645969-bfb4-47a4-b327-89502a44f6f7 实证 bug：中文 base + 中文骨架 +
    中文转写下 qwen-plus 完全镜像中文 EN directive 失效。改两步式后 EN base 必须
    显式承认 base 是中文骨架（"written in Chinese"），并要求翻译后再填
    （"translate" / "translated skeleton"）。few-shot 示例把两步过程走一遍让
    LLM 走 in-context 而不是听尾部 directive。

    用正则确保三件事实同时出现：
    - "chinese"（承认 base / skeleton 是中文）
    - "skeleton"（指向骨架本体——两步式的核心对象）
    - "translate"（要求翻译骨架成英文）
    反向：禁止偷渡成"do not" / "don't translate"否定形式。
    """
    body = _report_system("en").lower()
    # 正向：chinese + skeleton + translate 共现且非"do not"形态。
    # 跨度 300 字符略松是为了给将来措辞微调留余地——同事评审认可此权衡。
    pos_pattern = re.compile(
        r"\bchinese\b[\s\S]{0,300}?\bskeleton\b[\s\S]{0,300}?(?<!do not )(?<!don't )\btranslat\w*\b"
    )
    assert pos_pattern.search(body), (
        f"en base 未把中文骨架声明为「待翻译成英文」——qwen-plus 会镜像中文：{body!r}"
    )
    # 反向：禁止"do not / don't ... translate ... chinese ... skeleton"否定形式。
    assert not re.search(
        r"\b(?:do\s+not|don't|do\s+n't)\b[\s\S]{0,80}?\btranslat\w*\b[\s\S]{0,80}?\bchinese\b[\s\S]{0,80}?\bskeleton\b",
        body,
    ), (
        f"en base 被偷渡成「do not translate ... chinese ... skeleton」否定形式——两步式策略被破坏：{body!r}"
    )
    # 允许"do not translate"出现在 EXEMPT 上下文（"do not translate the pre-filled
    # {{session.X}} values" 是 EN base 里合法的措辞——保护预填 metadata），
    # 但禁止泛指"do not translate ... chinese ... skeleton"。上面那条反向断言已覆盖。


def test_en_directive_instructs_placeholder_wrapper_deletion():
    """显式要求 LLM 删除 {{ }} 包装——这是结构但语言中立的规则，必须正面重申
    否则 base prompt 的中文"删包装"规则在 en 输出时被 LLM 当成"语言内容"丢掉。

    EN 模式：删包装规则现在写在 _REPORT_SYSTEM_EN 里（两步式 Key rules 节）。
    测试查的是 _report_system("en") 整体（case-insensitive），不再 case-sensitive。
    """
    body = _report_system("en").lower()
    # 措辞演进：原"delete the `{{` and `}}` wrappers"已并入 EXEMPT-aware 的版本里
    # 以"delete both the `{{` and `}}` markers"形式出现。两者都视为满足硬要求。
    has_delete_phrase = (
        "delete both the `{{` and `}}` markers" in body
        or "delete the `{{` and `}}` wrappers" in body
    )
    assert has_delete_phrase, (
        f"en base 未显式要求删除 {{ }} 包装——{{ }} 兜底仅靠 _strip_orphan_placeholders 会丢语义上下文：{body!r}"
    )


def test_en_directive_enumerates_exempt_placeholders():
    """直接列出 EXEMPT 类别（session.X / skill:），让 LLM 不会泛化"删包装"
    到这两类。同时验证"OPS+ET" 措辞——同事评审指出「删除与保留挨太近会误读」
    之后已物理分开。
    """
    body = _report_system("en").lower()
    # "exempt" 这个关键词必须出现在 en 指令里（明示豁免）
    assert "exempt" in body, f"en 指令未明确豁免占位符列表：{body!r}"
    # 两种豁免类别必须分别点名
    assert "{{session.x}}" in body or "session.x" in body, (
        f"en 指令未点名 {{session.X}} 豁免：{body!r}"
    )
    assert "skill:" in body, f"en 指令未点名 skill 豁免：{body!r}"


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

    修复 ce645969 案例后 EN 模式改了：兜底短语写在 _REPORT_SYSTEM_EN 里（两步式
    Key rules 节 "Not mentioned in this interview."），不再写在 directive 末尾——
    同事 d753c98 当时 directive 在尾部追加，所以 directive 必须内嵌；现在 EN 模式
    base 整体英文化，base 自带兜底短语已让 LLM 看到。

    检查口径改为：fallback 短语必须在 LLM 实际看到的完整 prompt 里
    （_report_system(lang) 整体）。zh_cn directive 为空跳过——兜底从入参层
    `_fill_dangling_labels(md, language="zh_cn")` 注入，与 directive 解耦。
    """
    for lang, directive in _REPORT_LANG_INSTRUCTION.items():
        if not directive:
            continue  # 空 directive 默认走 base prompt + zh_cn 短语
        full_prompt = _report_system(lang)
        assert _FALLBACK_BY_LANG[lang] in full_prompt, (
            f"语种 {lang!r} 的完整 prompt 未内嵌兜底短语 {_FALLBACK_BY_LANG[lang]!r}；"
            f"LLM 看不到 fallback，会用 base 示例里的其他语种短语"
        )


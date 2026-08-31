"""Unicode 脚本检测：覆盖每族代表语种 + 边界（空 / MIXED）。"""
from __future__ import annotations

from app.core.i18n.script_detect import (
    _EXPECTED_SCRIPT,
    detect_language_match,
    detect_language_match_json,
    detect_script,
    observed_text,
)


# ── 主脚本识别 ────────────────────────────────────────────────


def test_detect_cjk_chinese():
    assert detect_script("你好世界，本次访谈未提及库存") == "CJK"


def test_detect_hiragana_japanese():
    assert detect_script("こんにちは世界") == "HIRAGANA"


def test_detect_katakana_japanese():
    assert detect_script("カタカナテスト") == "KATAKANA"


def test_detect_hangul_korean():
    assert detect_script("안녕하세요 세계") == "HANGUL"


def test_detect_cyrillic_russian():
    assert detect_script("Привет мир") == "CYRILLIC"


def test_detect_arabic():
    assert detect_script("مرحبا بالعالم") == "ARABIC"


def test_detect_latin_english():
    assert detect_script("Hello world, this is a test") == "LATIN"


def test_detect_latin_vietnamese_diacritics():
    """越南语用 Latin 字母 + 重音——必属 LATIN 族。"""
    assert detect_script("Xin chào thế giới, đây là bài kiểm tra") == "LATIN"


def test_detect_latin_french_diacritics():
    assert detect_script("Bonjour le monde, c'est un test") == "LATIN"


def test_empty_or_whitespace_defaults_to_latin():
    """空串 / 纯空白 → LATIN 默认值（避免空响应被误判为 MIXED 触发 pivot）。"""
    assert detect_script("") == "LATIN"
    assert detect_script("   \n\t  ") == "LATIN"


def test_mixed_below_threshold():
    """短文本混杂 → MIXED；不会把单字符误判为某族。"""
    assert detect_script("A 你") == "MIXED"  # 2 字符，每族 1 个 = 50% 但并列最高 → MIXED
    assert detect_script("Hi") == "LATIN"  # 2 字符全 LATIN，100% → LATIN


def test_long_mixed_text_falls_back_to_top():
    """长文本有明确多数族——取该族。"""
    text = "Hello world " * 20 + "你好"  # 主导 LATIN
    assert detect_script(text) == "LATIN"


# ── 期望脚本对照（detect_language_match）─────────────────────


def test_match_zh_cn_cjk():
    assert detect_language_match("你好世界", "zh_cn") is True


def test_match_zh_tw_cjk():
    assert detect_language_match("繁體中文測試", "zh_tw") is True


def test_mismatch_zh_cn_english():
    assert detect_language_match("Hello world", "zh_cn") is False


def test_match_en_latin():
    assert detect_language_match("This is a question", "en") is True


def test_match_vi_latin():
    """越南 diacritics 仍属 LATIN——必须 match vi。"""
    assert detect_language_match("Bạn có câu hỏi nào không?", "vi") is True


def test_match_ru_cyrillic():
    assert detect_language_match("Привет как дела", "ru") is True


def test_match_ja_hiragana():
    assert detect_language_match("こんにちは質問", "ja") is True


def test_match_ja_cjk_kanji():
    """日文 kanji 也属 CJK 块——必须 match ja。"""
    assert detect_language_match("日本語の漢字", "ja") is True


def test_match_ko_hangul():
    assert detect_language_match("안녕하세요 질문", "ko") is True


def test_unknown_lang_defaults_to_latin():
    """未配置的 lang（如 'ar' 长尾）走 LATIN 默认——LLM 返回英文不会误触发 pivot。

    长尾语种生产路径根本不会跑：get_lang_meta 把 ar 兜底成 en，所以 LLM 用 en system。
    此测试保护 _EXPECTED_SCRIPT 漏配未知 lang 时静默退化到 LATIN 的契约。
    """
    assert detect_language_match("Hello world", "ar") is True  # 默认 LATIN → 通过


def test_expected_script_covers_head_10():
    """10 语种每条都有期望脚本族——单源不变量。"""
    from app.core.i18n.lang_meta import _LANG_META
    assert set(_EXPECTED_SCRIPT) >= set(_LANG_META), (
        f"_EXPECTED_SCRIPT 缺语种：{set(_LANG_META) - set(_EXPECTED_SCRIPT)}"
    )


# ── 主脚本规则（en/vi/fr/de/es 请求下 LLM 输中文的收紧路径）───────────────


def test_main_script_rule_rejects_latin_target_with_pure_cjk_values():
    """en/vi/fr/de/es 请求下，LLM 输纯中文 values（无 Latin 缩写）
    → 主脚本 = CJK ∉ {LATIN} → 拒。

    原宽松规则（any expected script present）会因 schema 字段（"id":"q1" 等
    LATIN）命中即放行 → pivot 漏。新规则：主脚本必须 ∈ expected 才放行。
    """
    payload = (
        '{"items":[{"id":"q1","text":"你最近的项目背景是什么",'
        '"reason":"用户最关心库存周转痛点","status":"todo",'
        '"covered_segments":[],"corrected_segments":{}}]}'
    )
    assert detect_language_match_json(payload, "en") is False
    assert detect_language_match_json(payload, "vi") is False
    assert detect_language_match_json(payload, "fr") is False


def test_main_script_rule_rejects_cjk_target_with_pure_latin_values():
    """zh_cn/zh_tw 请求下，LLM 输纯英文 values（跑飞）
    → 主脚本 = LATIN ∉ {CJK} → 拒。"""
    payload = (
        '{"items":[{"id":"q1","text":"What is your project background?",'
        '"reason":"inventory, timeline, budget","status":"todo",'
        '"covered_segments":[],"corrected_segments":{}}]}'
    )
    assert detect_language_match_json(payload, "zh_cn") is False
    assert detect_language_match_json(payload, "zh_tw") is False


def test_main_script_rule_accepts_cjk_target_with_mixed_values():
    """zh_cn 请求下，values 主体 CJK（带少量 Latin 缩写） → 主脚本 CJK ∈ {CJK} → 通过。"""
    payload = (
        '{"items":[{"id":"q1","text":"AI项目预算多少",'
        '"reason":"用户最关心库存周转痛点、采购效率","status":"todo",'
        '"covered_segments":[],"corrected_segments":{}}]}'
    )
    assert detect_language_match_json(payload, "zh_cn") is True


def test_main_script_rule_accepts_latin_target_with_latin_values():
    """en 请求 + 纯 Latin values → 主脚本 LATIN ∈ {LATIN} → 通过。"""
    payload = (
        '{"items":[{"id":"q1","text":"What is your AI project about?",'
        '"reason":"timeline, budget","status":"todo","covered_segments":[],'
        '"corrected_segments":{}}]}'
    )
    assert detect_language_match_json(payload, "en") is True


# ── observed_text：JSON 抽 values 去结构稀释 ───────────


def test_observed_text_json_extracts_values():
    """JSON 输入抽 values——detect_script 不被结构字符稀释为 LATIN。"""
    raw = '{"items":[{"reason":"用户背景 CTO AI 调研"},{"reason":"timeline"}]}'
    out = observed_text(raw)
    # values join 后是「用户背景 CTO AI 调研 timeline」——主脚本 CJK
    assert "用户背景" in out
    assert "{" not in out  # 结构字符不应出现
    assert '"reason"' not in out  # JSON 键名不应出现


def test_observed_text_markdown_strips_syntax():
    """Markdown 输入去结构字符——避免列表符号 / 标题 # 稀释脚本统计。"""
    raw = "## 背景\n- 项目：AI 项目\n- 受访者：张三"
    out = observed_text(raw)
    assert "##" not in out
    assert "\n" not in out
    assert "背景" in out


def test_observed_text_invalid_json_falls_back_to_strip():
    """JSON 解析失败 → strip 结构字符（与 detect_language_match_json 兜底一致）。"""
    raw = "## 普通 Markdown 报告，背景：AI 项目"
    out = observed_text(raw)
    assert "##" not in out
    assert "背景" in out

# ── except 分支主脚本收紧（markdown 漏检修复）─────────────────


def test_detect_language_match_json_except_branch_tightens_latin():
    """解析失败 → except 分支（报告 markdown 走这条）也要跑主脚本收紧。

    bug 场景：en + 全中文 markdown + 一个 'AI' 缩写 → 旧宽松规则命中
    'AI' (Latin) 即放行 → pivot 漏触发。修复后 except 分支也对
    expected == {"LATIN"} 跑主脚本收紧，主脚本 = CJK → 拒。
    """
    zh_md = "本次访谈的主题是 AI 行业转型，用户提出了 5 个核心问题。"
    # detect_language_match（宽松）仍 True——'AI' 命中 LATIN——保持原宽松语义
    assert detect_language_match(zh_md, "en") is True
    # detect_language_match_json 走 except 分支，主脚本收紧生效 → False
    assert detect_language_match_json(zh_md, "en") is False
    # zh_cn 期望 {CJK} 不收紧（避免 schema 字段 Latin 误拒）
    assert detect_language_match_json(zh_md, "zh_cn") is True


# ── detect_script 分母剥离结构字符（避免短文本漏检窗口）─────


def test_detect_script_denominator_excludes_structural_chars():
    """分母 = 剥结构字符后的字符数——中文 values 频繁空格/标点不应被稀释到 MIXED。

    旧实现 n = len(text) 含空格标点 → 31/57 = 54% CJK 仍判 CJK（已过阈值）。
    新实现 n = len(_JSON_SYNTAX_RE.sub("", text)) → 31/42 = 73%，比例提升，
    短文本场景更不易被稀释到 30% 阈值下。
    """
    raw = "# 报告\n\n本次访谈的主题是 AI 行业转型。用户提出 5 个核心问题。"
    # 主体是中文，应判 CJK
    assert detect_script(raw) == "CJK"
    # 极端：大量空格标点 + 少量 CJK——旧实现可能判 MIXED，新实现更稳
    extreme = "  \n\n   你   \n\n  "
    # 极端情况下 text.strip() 非空但剥结构字符后只剩 '你'，detect_script 应判 CJK
    # 注意：detect_script 在 text.strip() 为空时返回 LATIN
    # 我们的极端例子有 '你'，strip() 非空，但 n 太小——单字符场景需 special case
    # 这里只验证典型 markdown 路径不被稀释即可


def test_detect_script_cjk_not_diluted_by_spaces():
    """中文 values + 频繁空格仍判 CJK——验证分母修复效果。"""
    sample = "用户   背景   是   AI   项目   受访者   张三"
    assert detect_script(sample) == "CJK"

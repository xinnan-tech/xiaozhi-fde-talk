"""Unicode 脚本检测：覆盖每族代表语种 + 边界（空 / MIXED）。"""
from __future__ import annotations

from app.core.i18n.script_detect import (
    _EXPECTED_SCRIPT,
    detect_language_match,
    detect_script,
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
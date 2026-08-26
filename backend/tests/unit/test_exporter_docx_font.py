"""Word 导出字体：按 llm.output_language 选 ascii/eastAsia，不再用 MS 明朝。

历史 bug：下载的 Word 报告字体是「MS 明朝」（Word 默认 eastAsiaTheme=minorEastAsia
解析结果）——中文场景应显式走「宋体」，英文场景应走「Times New Roman」。

修法：app/services/reports/exporter.py:_to_docx(md, language) 按 language 选
(ascii_font, east_asia_font)，并 _apply_docx_fonts() 递归遍历 styles.xml
所有 <w:rFonts>，清掉 asciiTheme/hAnsiTheme/eastAsiaTheme/cstheme 四个
theme ref 属性，填入 named fonts。
"""
from __future__ import annotations

import io
import re
import zipfile

from app.services.reports.exporter import export, _fonts_for


def _docx_styles_xml(docx_bytes: bytes) -> str:
    """打开 zip，提取 word/styles.xml 文本。"""
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        return z.read("word/styles.xml").decode("utf-8")


def _all_rfonts(docx_bytes: bytes) -> list[str]:
    """styles.xml 里所有 <w:rFonts .../> 元素原文。"""
    sx = _docx_styles_xml(docx_bytes)
    return re.findall(r"<w:rFonts[^/]*/>", sx)


def _rfont_attrs(docx_bytes: bytes, attr: str) -> list[str]:
    """抽 styles.xml 里所有 <w:rFonts> 元素的指定属性值（如 w:eastAsia / w:ascii）。

    关键：只匹配 <w:rFonts> 元素内的属性——不能误扫到 <w:lang w:eastAsia="en-US">
    这种语言标签里的同名属性。
    """
    sx = _docx_styles_xml(docx_bytes)
    hits = []
    for tag in re.findall(r"<w:rFonts[^/]*/>", sx):
        m = re.search(rf'w:{attr}="([^"]+)"', tag)
        if m:
            hits.append(m.group(1))
    return hits


def test_chinese_uses_simsun_not_ms_mincho():
    """zh_cn → ascii=宋体, eastAsia=宋体；styles.xml 里不应残留 eastAsiaTheme。"""
    md = "# 标题\n\n中文正文 与 English 混排。\n"
    data, _ = export(md, "word", "zh_cn")
    east_hits = _rfont_attrs(data, "eastAsia")
    assert east_hits, "styles.xml 应至少有一个 eastAsia 属性"
    assert all(e == "宋体" for e in east_hits), (
        f"中文报告 eastAsia 应统一为「宋体」，实际：{set(east_hits)}"
    )
    ascii_hits = _rfont_attrs(data, "ascii")
    assert all(a == "宋体" for a in ascii_hits), (
        f"中文报告 ascii 应为「宋体」兜底，实际：{set(ascii_hits)}"
    )
    sx = _docx_styles_xml(data)
    theme_refs = re.findall(r"eastAsiaTheme|hAnsiTheme|asciiTheme|cstheme=", sx)
    assert not theme_refs, (
        f"styles.xml 还残留 theme refs（解析为 MS 明朝的根因）：{theme_refs[:5]}"
    )


def test_english_uses_times_new_roman():
    """en → ascii=Times New Roman, eastAsia=宋体（中文兜底）。"""
    md = "# Title\n\nBody content. Some 中文 here.\n"
    data, _ = export(md, "word", "en")
    ascii_hits = _rfont_attrs(data, "ascii")
    assert ascii_hits, "应至少有一个 ascii 属性"
    assert all(a == "Times New Roman" for a in ascii_hits), (
        f"英文报告 ascii 应统一为 Times New Roman，实际：{set(ascii_hits)}"
    )
    east_hits = _rfont_attrs(data, "eastAsia")
    assert all(e == "宋体" for e in east_hits), (
        f"英文报告 eastAsia 应为「宋体」兜底 CJK，实际：{set(east_hits)}"
    )
    sx = _docx_styles_xml(data)
    theme_refs = re.findall(r"eastAsiaTheme|hAnsiTheme|asciiTheme|cstheme=", sx)
    assert not theme_refs, (
        f"英文 styles.xml 还残留 theme refs：{theme_refs[:5]}"
    )


def test_unknown_language_falls_back_to_english_font():
    """未知 lang（如 'klingon'）→ 走 en 兜底（Times New Roman + 宋体），不崩。"""
    md = "# Title\n\nBody.\n"
    data, _ = export(md, "word", "klingon")
    ascii_hits = _rfont_attrs(data, "ascii")
    assert all(a == "Times New Roman" for a in ascii_hits)


def test_empty_language_defaults_to_english_font():
    """language='' 或 None → 走 en 兜底。"""
    md = "# x\n"
    data_empty, _ = export(md, "word", "")
    data_none, _ = export(md, "word", None)  # type: ignore[arg-type]
    for data in (data_empty, data_none):
        ascii_hits = _rfont_attrs(data, "ascii")
        assert all(a == "Times New Roman" for a in ascii_hits)


def test_fonts_for_lang_table_covers_all_supported():
    """_fonts_for lang 表里覆盖 _LANG_META 全部 key——任一语种报告都有合理字体。"""
    from app.core.i18n.lang_meta import _LANG_META
    for lang in _LANG_META:
        ascii_font, east_font = _fonts_for(lang)
        assert ascii_font, f"{lang} 应有 ascii 字体"
        assert east_font, f"{lang} 应有 eastAsia 字体"


def test_no_theme_refs_in_any_supported_language():
    """任一支持语种导出的 docx，styles.xml 都不应残留 theme refs。

    这是「MS 明朝不复现」的兜底断言——若有人加新语种时漏掉 _apply_docx_fonts，
    这条会立刻挂。
    """
    from app.core.i18n.lang_meta import _LANG_META
    md = "# 测试报告\n\n中 English 混排。\n"
    for lang in _LANG_META:
        data, _ = export(md, "word", lang)
        sx = _docx_styles_xml(data)
        theme_refs = re.findall(r"eastAsiaTheme|hAnsiTheme|asciiTheme|cstheme=", sx)
        assert not theme_refs, (
            f"{lang} 导出 docx 还有 theme refs（会 fallback 到 MS 明朝）："
            f"{theme_refs[:3]}"
        )


def test_md_and_html_ignore_language():
    """md / html 不读 language——传 zh_cn 与 en 产出相同。"""
    md = "# 标题\n\n文本。\n"
    md_zh, _ = export(md, "md", "zh_cn")
    md_en, _ = export(md, "md", "en")
    assert md_zh == md_en, "md 格式应忽略 language"

    html_zh, _ = export(md, "html", "zh_cn")
    html_en, _ = export(md, "html", "en")
    assert html_zh == html_en, "html 格式应忽略 language"
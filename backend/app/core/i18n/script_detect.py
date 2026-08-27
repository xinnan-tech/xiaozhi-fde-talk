"""Unicode 脚本检测：判断 LLM 输出文本的主脚本，与目标语种预期脚本对照。

阈值：占 30%+ 的字符属该脚本族才算「主脚本」；低于阈值视为 MIXED（多语种
混杂或短文本）。空串 / 纯标点 → LATIN（默认值，避免 pivot 把空响应误判）。

覆盖脚本族：CJK（简繁 + 日韩汉字）、HIRAGANA、KATAKANA、HANGUL、CYRILLIC、
ARABIC、LATIN（覆盖英文 + 西欧 + 越南——越南语用拉丁字母 + 重音 diacritics，
与英文共享 Latin 块但带重音）。
"""
from __future__ import annotations

import json
import re

# 各 Unicode 脚本的字符范围——按段粗粒度切，足够区分 CJK / 西文 / 西里尔等。
# CJK 仅取 BMP 主块（U+3400-U+9FFF：ExtA + Unified）——避开 Hangul Syllables
# (U+AC00-U+D7A3) 与 CJK Compatibility Ideographs (U+FA0E-U+FAFF) 的重叠区。
_CJK_RE = re.compile(r"[㐀-鿿]")
_HIRAGANA_RE = re.compile(r"[぀-ゟ]")
_KATAKANA_RE = re.compile(r"[゠-ヿ]")
_HANGUL_RE = re.compile(r"[가-퟿]")  # Hangul Syllables U+AC00-U+D7A3
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿ]")
# Latin 扩展：含 A-Za-z + Latin-1 Supplement + Latin Extended-A/B（覆盖越南重音）。
_LATIN_RE = re.compile(r"[A-Za-zÀ-ʯ̀-ͯ]")

# 名称 → compiled regex，detect_language_match 用 search 加速（任一匹配即放行）。
_SCRIPT_REGEX = {
    "CJK": _CJK_RE,
    "HIRAGANA": _HIRAGANA_RE,
    "KATAKANA": _KATAKANA_RE,
    "HANGUL": _HANGUL_RE,
    "CYRILLIC": _CYRILLIC_RE,
    "ARABIC": _ARABIC_RE,
    "LATIN": _LATIN_RE,
}

# 结构中立字符：JSON 结构符号 + Markdown 列表/标题符号 + 空白——脚本中立，
# 剔除避免比例稀释成 LATIN 主导。coaching JSON 输出 + 报告 Markdown 输出都走这条。
# 位置：必须在 detect_script 之前——detect_script 用它做主脚本占比的分母。
_JSON_SYNTAX_RE = re.compile(r"[\s{}\[\]\":,#*\-]")


def detect_script(text: str) -> str:
    """返回主脚本名：CJK / HIRAGANA / KATAKANA / HANGUL / CYRILLIC / ARABIC
    / LATIN / MIXED。空串 → LATIN（默认值，避免空响应被误判）。

    分母 = 剥离结构字符后的字符数：避免「中文 values 频繁空格/标点」被稀释到
    30% 阈值以下判 MIXED（MIXED 豁免主脚本收紧规则，留漏检窗口）。
    """
    if not text or not text.strip():
        return "LATIN"
    n = len(_JSON_SYNTAX_RE.sub("", text))
    scores = {
        "CJK": len(_CJK_RE.findall(text)),
        "HIRAGANA": len(_HIRAGANA_RE.findall(text)),
        "KATAKANA": len(_KATAKANA_RE.findall(text)),
        "HANGUL": len(_HANGUL_RE.findall(text)),
        "CYRILLIC": len(_CYRILLIC_RE.findall(text)),
        "ARABIC": len(_ARABIC_RE.findall(text)),
        "LATIN": len(_LATIN_RE.findall(text)),
    }
    top_script, top_count = max(scores.items(), key=lambda kv: kv[1])
    # 并列最高分（其他脚本 count == top_count）→ MIXED：短文本双族混杂没明确多数。
    runner_up = max((c for s, c in scores.items() if s != top_script), default=0)
    if top_count == runner_up:
        return "MIXED"
    if top_count / n >= 0.3:
        return top_script
    return "MIXED"


# 期望脚本族：每条 lang → 接受的脚本集合——Latin 语种都允许 LATIN 主导。
# ja 同时接受 CJK（kanji 汉字）、HIRAGANA、KATAKANA、LATIN（拉丁字母转写）。
# ru / ko 同理允许拉丁转写混入。
_EXPECTED_SCRIPT: dict[str, set[str]] = {
    "zh_cn": {"CJK"},
    "zh_tw": {"CJK"},
    "en":    {"LATIN"},
    "vi":    {"LATIN"},
    "ru":    {"CYRILLIC", "LATIN"},
    "ko":    {"HANGUL", "LATIN"},
    "ja":    {"HIRAGANA", "KATAKANA", "CJK", "LATIN"},
    "fr":    {"LATIN"},
    "de":    {"LATIN"},
    "es":    {"LATIN"},
    # 长尾语种（不在 _LANG_META，get_lang_meta 走 en 兜底）——不在 _EXPECTED_SCRIPT。
}


def detect_language_match(text: str, expected_lang: str) -> bool:
    """LLM 输出文本中是否存在 expected_lang 接受脚本族的任一脚本——任意出现即放行。

    规则比「主脚本」更宽松：JSON 输出常含 JSON 键（"id"/"text"/"status" 等固定
    LATIN），即使 LLM 写对了目标语种，主脚本比例仍可能被 LATIN 稀释触发误 pivot。
    只要 expected 脚本族任一出现（即 LLM 真的写过那个语种的字），就视为合格。

    空文本默认接受——避免空响应误触发 pivot；空响应走 _fill_dangling_labels 兜底。
    """
    expected = _EXPECTED_SCRIPT.get((expected_lang or "").lower(), {"LATIN"})
    if not text:
        return True
    for script in expected:
        if _SCRIPT_REGEX[script].search(text):
            return True
    return False


def _collect_string_values(node) -> list[str]:
    """递归收集 JSON 树的所有字符串值。"""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        out: list[str] = []
        for v in node.values():
            out.extend(_collect_string_values(v))
        return out
    if isinstance(node, list):
        out = []
        for v in node:
            out.extend(_collect_string_values(v))
        return out
    return []


def observed_text(text: str) -> str:
    """提取用于日志的脚本可观察文本：JSON 抽 values，Markdown 去结构字符。

    detect_script 按字符统计脚本占比；JSON 输出含大量结构字符（{ } [ ] " : , 空格）
    都是 LATIN 块，把实际语种占比稀释→日志误导（恒判 LATIN）。
    """
    try:
        parsed = json.loads(text)
        values = _collect_string_values(parsed)
        if values:
            return " ".join(values)
    except (ValueError, TypeError):
        pass
    return _JSON_SYNTAX_RE.sub("", text or "")


def detect_language_match_json(text: str, expected_lang: str) -> bool:
    """JSON 输出专用：解析后只对字符串值判脚本族——忽略 JSON 键名（"id"/"text"
    等结构字段固定 LATIN，会把整体比例稀释成 LATIN 主导触发误 pivot）。

    主脚本校验收紧：除了「expected 脚本族任一出现」（detect_language_match 的
    「any script in expected」宽松规则），先跑 detect_script(values) 拿主脚本；
    主脚本不在 expected 且不是 MIXED → 拒。bug 主场景：en/vi/fr/de/es 请求下
    LLM 输出全中文 reason（含 AI/CTO/10K 等
    Latin 缩写），原宽松规则因 Latin 缩写命中即放行 → pivot 漏触发；新规则
    主脚本 = CJK ∉ {LATIN} → 拒。

    MIXED 仍走宽松规则：短文本双族混杂（中文 + Latin 缩写）属正常，不应误拒。

    解析失败兜底为 strip 结构字符后判（Markdown 路径也走这个分支）。
    """
    expected = _EXPECTED_SCRIPT.get((expected_lang or "").lower(), {"LATIN"})
    try:
        parsed = json.loads(text)
        values = _collect_string_values(parsed)
        if not values:
            return detect_language_match(text, expected_lang)
        joined = " ".join(values)
        # 主脚本收紧：仅对 expected = {LATIN}（en/vi/fr/de/es）收紧。bug 主场景：
        # en 请求下 LLM 输中文 values（schema 字段是 Latin，会命中原宽松
        # {LATIN} 集合），主脚本 = CJK ∉ {LATIN} → 拒。
        # zh_cn/zh_tw 期望 {CJK}：schema 字段 Latin 会拉低 CJK 比例到主脚本 = LATIN，
        # 此场景下宽松规则（detect_language_match 命中 CJK content 字段）已足够，
        # 收紧会因 schema 字段稀释误拒正常 content 输出。
        main_script = detect_script(joined)
        if expected == {"LATIN"} and main_script not in expected and main_script != "MIXED":
            return False
        return detect_language_match(joined, expected_lang)
    except (ValueError, TypeError):
        stripped = _JSON_SYNTAX_RE.sub("", text or "")
        # 主脚本收紧也适用于 except 分支：报告 markdown 走这条（解析失败 =
        # 非 JSON 形态 = 自由文本）。已剥结构字符，无 JSON 键名稀释风险——
        # JSON 分支担心的「schema 字段 Latin 拉低 CJK 比例」在此场景不存在。
        main_script = detect_script(stripped)
        if expected == {"LATIN"} and main_script not in expected and main_script != "MIXED":
            return False
        return detect_language_match(stripped, expected_lang)


# 键集合同步债：_EXPECTED_SCRIPT 与 _LANG_META 必须一一对应——任何 lang 漏写
# 都会让该 lang 走默认 {LATIN} 集合（detect_language_match line 90），被
# 静默接受任何文本，从而 pivot 失效。import 期 fail-fast 比单测更早暴露。
from app.core.i18n.lang_meta import _LANG_META  # noqa: E402
assert set(_EXPECTED_SCRIPT) == set(_LANG_META), (
    "_EXPECTED_SCRIPT 键集合必须等于 _LANG_META："
    f"expected={set(_EXPECTED_SCRIPT)} vs lang_meta={set(_LANG_META)}"
)
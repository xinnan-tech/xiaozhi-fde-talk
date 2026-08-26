"""锁死报告页 stats 不再硬编码 '--'，从已拿到的 transcript/items/coverage 现算。

历史 bug：frontend/src/views/report/index.vue 的 stats computed 三块数据
（问题覆盖、转录文本、对话轮数）一直是硬编码 '--'，从未从后端拿真实值。

修复后 stats computed 从 interviewDetail 的 transcript + items + coverage 派生：
- question_coverage: items 里 status=='done' 且 coverage[id] 非空的比例（%）
- transcript_chars: sum(seg.corrected_text?.length ?? seg.text?.length ?? 0)
- dialogue_turns: transcript.length

覆盖率口径与 backend/app/transport/http/routes/interviews.py:67-73 列表接口
的 _session_summary 保持一致（避免报告页/列表页两处数字打架）。
转录文本口径与 backend/app/services/reports/generator.py:232-235 _seg_text 一致
（corrected_text 优先 > text）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_VUE = ROOT / "src" / "views" / "report" / "index.vue"


def _script_block(text: str) -> str:
    """提取 <script setup> 块内容（用于独立检查 stats computed）。"""
    start = text.index("<script")
    end = text.index("</script>", start)
    return text[start:end]


def test_stats_no_longer_hardcoded_dashes():
    """stats computed 三块 value 不再硬编码 '--'。"""
    text = REPORT_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    # 旧 bug 形态：{ value: "--", ... 出现 3 次
    assert 'value: "--"' not in script, (
        "report/index.vue stats computed 还在硬编码 '--'；"
        "应从 interviewDetail.transcript/items/coverage 现算"
    )


def test_stats_computed_reads_from_interview_detail():
    """stats computed 必须依赖 interviewDetail 的三个字段。"""
    text = REPORT_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    # 三个派生口径都得在 stats 计算里出现
    for marker in ("interviewDetail", "transcript", "coverage", "items"):
        assert marker in script, f"stats 计算缺依赖：{marker}"


def test_stats_unit_labels_unchanged():
    """i18n 单位标签保持原文（% / characters_unit / turns_unit），不能顺手改。"""
    text = REPORT_VUE.read_text(encoding="utf-8")
    assert '"%"' in text
    assert "characters_unit" in text
    assert "turns_unit" in text


def test_stats_label_keys_unchanged():
    """i18n 三个 label key（coverage/transcript/conversations）保持不变。"""
    text = REPORT_VUE.read_text(encoding="utf-8")
    assert "report.stats.coverage" in text
    assert "report.stats.transcript" in text
    assert "report.stats.conversations" in text
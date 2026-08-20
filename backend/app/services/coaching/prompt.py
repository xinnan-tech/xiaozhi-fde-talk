"""辅导 prompt 组装（system + user）。

输入顺序：system + transcript 在前/稳定，清单/跳过在后/易变。

Stage 3 单一英文 base 后：所有语种共用同一段 _OUTPUT_RULE / _FIRST_OUTPUT_RULE，
差异仅在 format 占位符值注入（lang_native / lang_english / lang_bcp47）。
"""
from __future__ import annotations

import json

from app.core.i18n.lang_meta import derived_fallback_phrases, get_lang_meta
from app.domain.session import Session, TranscriptSegment
from app.domain.template import Template
from app.services.sessions.state import SessionState

# 唯一 _STYLE_RULE_BASE：英文版（原来 _STYLE_RULE_BASE_EN 提升）。语言中立措辞规则——
# ~20 words / comma-separated keywords / no honorifics / no preamble——所有语种共用。
# "~20 words" 注：CJK 语种（zh_cn/zh_tw/ja/ko）words ≠ characters——LLM 在 CJK 下应
# 视「words ≈ characters × 0.5–1」自行换算；不要字面照搬「20 字」。
_STYLE_RULE_BASE = """
- `text`: a concise, conversational question in your output language — at most ~20 words (~30 characters for CJK languages where word count is ambiguous), one point per question. No honorifics, greetings, thanks, or preamble ("Manager Peng,", "Hello,", "Thanks for your time"). Don't cram multiple alternatives into one question ("Is it A, B, or C?") — put candidate directions in `reason`.
- `reason`: ≤15 words of key points; comma-separated keywords; no prefixes like "Direction:" or "Already clear:". Give `reason` for every item (self-explanatory questions may be brief).
- For todo/new items, `reason` should describe dimension or candidate types (e.g. "timeline, budget range", "CTO / Sales VP"), NOT made-up specifics (numbers, dates, names, compliance regimes) — only write what's actually in the interview's basic info.
- Reference style: `text` "What specifically should the AI help you with?" `reason` "transcription / prompting / reports"."""

# 会中重算才有 done 条目：在 base 上追加 done 的 reason 语义与示例。
_STYLE_RULE = _STYLE_RULE_BASE + """
- For `done` items, `reason` writes "topic: conclusion"; topic 2-3 words; conclusion MUST NOT repeat the question (e.g. `text` "Roughly what budget?" `reason` "Budget: 10K RMB/year, tight control")."""

_OUTPUT_RULE = """Output ONLY a JSON object of this exact shape:
{{"items": [
  {{"id": "<id or null>", "text": "...", "status": "todo|done|new", "reason": "...", "covered_segments": ["s3"], "corrected_segments": {{"s3": "..."}}}}
]}}
Rules:
- status three states: `done` = already answered/covered in the conversation; `todo` = not yet covered; `new` = emerged in the conversation and must be clarified now.
- Keep existing item IDs; brand-new items get `id: null` (backend assigns).
- `done` MUST give `covered_segments` (list of `seg_id`s supporting it); non-`done` items give an empty array.
- Mark `done` whenever the conversation has already answered the substance — even if phrased differently or under another item's name; do not open new items for already-answered content.
- Surface newly-emerged must-ask points (`status=new`), not just tick-covered ones; but each recompute may add at most 2 `new` items, picking the most critical.
- Order items by suggested interview order, most urgent first.
- `done` MUST give a `reason` (≤15 word conclusion).
- For ASR errors / omissions in covered transcript, give your corrected version: field `corrected_segments` shape `{{"seg_id": "corrected text"}}`. **Only fill when substantively different from the original `text`**; skip if no correction. Rationale goes in `reason` (≤15 words). **Never rewrite the original meaning — only fix words/typos.**
- Only `done` may fill `corrected_segments`; non-`done` leaves `{{}}`.
""" + _STYLE_RULE


def _escape_xml(text: str) -> str:
    """转义用户输入中的 XML 特殊字符，防标签闭合注入。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_system(template: Template, goal: str | None, output_language: str = "zh_cn") -> str:
    """会中重算 prompt：基线 + transcript + 跳过 id → 更新后的完整清单。

    单一英文 base + 参数化指令注入。playbook（模板自定义中文内容）保留原状——
    它是模板自定义内容不是 LLM base，且 LLM 接收时会与 goal 一起作为 instruction 读。

    format 注入安全：template_text 先 .format()（语言占位符），再以字符串拼接追加
    goal_block / playbook——避免用户输入的 `{xxx}` 被 .format() 解析为 KeyError。
    """
    playbook = (template.coaching.playbook or "").strip()
    has_goal = bool(goal and goal.strip())
    goal_block = (
        f"\n<user_goal>\n{_escape_xml(goal.strip())}</user_goal>"
        if has_goal else ""
    )
    lang = (output_language or "zh_cn").lower()
    meta = get_lang_meta(lang)
    # 空 goal 时改写主句——避免「The goal has been provided」与实际不一致。
    goal_clause = (
        "The goal has been provided; use it together with the must_ask baseline to "
        "coach the interviewer in real time on what else to ask and what to follow up on."
        if has_goal else
        "Use the must_ask baseline to coach the interviewer in real time on what to ask "
        "and what to follow up on."
    )
    template_text = (
        f"You are a senior interview coach. You assist a product manager conducting a "
        f"needs-discovery / user interview. {goal_clause}\n\n"
        "You will receive: the full conversation transcript, the current question list, "
        "and the IDs skipped this turn (all wrapped in `<user_*>` tags). Output the "
        "**updated complete list**.\n\n"
        f"{_OUTPUT_RULE}\n\n"
        f"## Output language ({{lang_native}}, mandatory)\n"
        f"- Write all `text` and `reason` fields in {{lang_native}} ({{lang_english}}, {{lang_bcp47}}).\n"
        f"- The `<user_*>` blocks below may contain Chinese text (transcript, project / "
        f"interviewee / goal metadata, baseline must-ask, template playbook). Read them "
        f"as instructions and translate mentally into {{lang_native}}.\n"
        f"- Output ONLY the JSON object — no explanations, no code-block wrapping."
    )
    prompt = template_text.format(
        lang_native=meta.native_name,
        lang_english=meta.english_name,
        lang_bcp47=meta.bcp47,
    )
    # 动态内容（goal / playbook）拼到 format 之后——format 注入安全。
    parts = [prompt]
    if goal_block:
        parts.append(goal_block)
    if playbook:
        parts.append(f"\n<template_playbook>\n{_escape_xml(playbook)}\n</template_playbook>")
    return "\n\n".join(parts)


def build_user(state: SessionState) -> str:
    # 优先用 corrected_text：上次重算 LLM 给的纠错必须透传到下一次 LLM，
    # 否则下次重算 LLM 又把同一段当未答/继续追问，纠错就白做了。
    def _seg_text(s: TranscriptSegment) -> str:
        return s.corrected_text.strip() or s.text

    transcript = (
        "\n".join(f"[{s.seg_id}] {_seg_text(s)}" for s in state.transcript)
        or "（暂无对话）"
    )
    current = json.dumps(
        [{"id": it.id, "text": it.text, "status": it.status.value} for it in state.items],
        ensure_ascii=False,
    ) or "[]"
    skipped = sorted(state.skipped_ids)
    # 用户输入一律用 <user_*> 标签包裹 + 转义，与指令隔离防注入
    return (
        f"<user_transcript>\n{_escape_xml(transcript)}\n</user_transcript>\n\n"
        f"<user_progress>\n{_escape_xml(current)}\n</user_progress>\n\n"
        f"<user_skipped>{_escape_xml(','.join(skipped))}</user_skipped>\n\n"
        "Output the updated complete list now."
    )


# 首评 prompt：访谈尚未开始，据 base_info/goal + 模板基线生成第一批问题。
# 单一英文 base + JSON 结构示例（language-agnostic）演示翻译流程。
_FIRST_OUTPUT_RULE = """Output ONLY a JSON object of this exact shape:
{{"items": [
  {{"id": "<baseline id or null>", "text": "...", "status": "todo", "reason": "...", "covered_segments": [], "corrected_segments": {{}}}}
]}}
Rules:
- status is always `todo` for first-batch (no transcript yet).
- Each baseline must_ask entry MUST appear once in your output with the same `id` (customize its `text` to fit this interview's project / interviewee / goal — translate the Chinese wording into your output language; do NOT copy verbatim).
- Items semantically not in the baseline may use `id: null` (the backend assigns the id).
- Order the items by suggested interview order, 6-10 items total.
""" + _STYLE_RULE_BASE


def build_first_batch(template: Template, session: Session, output_language: str = "zh_cn") -> tuple[str, str]:
    """首评 prompt：访谈尚未开始，据 base_info/goal + 模板基线生成第一批问题。

    输出契约与重算同形（validate_llm_output 直接可用），区别仅在：无对话依据、
    id 尽量沿用基线、全部 todo、按发问顺序排列。

    单一英文 base + 语言参数化注入；few-shot 示例演示翻译流程（language-agnostic），
    避免示例语言与目标语种冲突。

    format 注入安全：template_text 先 .format()，再以字符串拼接追加 goal_block /
    playbook——避免用户输入的 `{xxx}` 被 .format() 解析为 KeyError。
    """
    goal = (session.goal or "").strip()
    has_goal = bool(goal)
    goal_block = (
        f"\n<user_goal>\n{_escape_xml(goal)}</user_goal>" if has_goal else ""
    )
    playbook = (template.coaching.playbook or "").strip()
    base = json.dumps(session.base_info or {}, ensure_ascii=False)
    baseline = json.dumps(
        [{"id": m.id, "text": m.text} for m in template.coaching.must_ask],
        ensure_ascii=False,
    )
    lang = (output_language or "zh_cn").lower()
    meta = get_lang_meta(lang)
    goal_clause = (
        "The goal has been provided; use it together with the must_ask baseline to "
        "coach the interviewer in real time on what else to ask and what to follow up on."
        if has_goal else
        "Use the must_ask baseline to coach the interviewer in real time on what to ask "
        "and what to follow up on."
    )
    template_text = (
        "You are a senior interview coach. You assist a product manager conducting a "
        f"needs-discovery / user interview. {goal_clause}\n\n"
        "The interview has not started yet (no transcript). You will receive: the "
        "interview's basic info and the template's baseline must-ask list (both wrapped "
        "in `<user_*>` tags). Output the **opening batch of questions** tailored to this "
        "specific interview.\n\n"
        f"{_FIRST_OUTPUT_RULE}\n\n"
        "## Example (JSON shape, translated to your output language)\n"
        "Input baseline (Chinese):\n"
        "[{{\"id\": \"objective\", \"text\": \"对方真正想达成什么（动机/目标）\"}}, "
        "{{\"id\": \"pain\", \"text\": \"痛点 / 未满足需求\"}}]\n"
        "Expected output (translated to your output language):\n"
        "{{\"items\": [\n"
        "  {{\"id\": \"objective\", \"text\": \"<question text in your output language>\", \"status\": \"todo\", \"reason\": \"<keywords in your output language>\", \"covered_segments\": [], \"corrected_segments\": {{}}}},\n"
        "  {{\"id\": \"pain\", \"text\": \"<question text>\", \"status\": \"todo\", \"reason\": \"<keywords>\", \"covered_segments\": [], \"corrected_segments\": {{}}}}\n"
        "]}}\n\n"
        "## Output language ({lang_native}, mandatory)\n"
        "- Write all `text` and `reason` fields in {lang_native} ({lang_english}, {lang_bcp47}).\n"
        "- The `<user_*>` blocks below may contain Chinese text (base info, baseline "
        "must-ask, goal, template playbook). Read them as instructions and translate "
        "mentally into {lang_native}.\n"
        "- Output ONLY the JSON object — no explanations, no code-block wrapping."
    )
    system = template_text.format(
        lang_native=meta.native_name,
        lang_english=meta.english_name,
        lang_bcp47=meta.bcp47,
    )
    parts = [system]
    if goal_block:
        parts.append(goal_block)
    if playbook:
        parts.append(f"<template_playbook>\n{_escape_xml(playbook)}\n</template_playbook>")
    system = "\n\n".join(parts)
    user = (
        f"<user_base_info>\n{_escape_xml(base)}\n</user_base_info>\n\n"
        f"<user_baseline>\n{_escape_xml(baseline)}\n</user_baseline>\n\n"
        "Output the opening batch of interview questions now."
    )
    return system, user
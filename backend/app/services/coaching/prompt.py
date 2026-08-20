"""辅导 prompt 组装（system + user）。

输入顺序：system + transcript 在前/稳定，清单/跳过在后/易变。
"""
from __future__ import annotations

import json

from app.domain.session import Session, TranscriptSegment
from app.domain.template import Template
from app.services.sessions.state import SessionState

_STYLE_RULE_BASE = """
措辞规则：
- text：≤20 字的口语化问句，一次只问一个点。不写称呼、问候、感谢、背景铺垫（如「彭经理，」「您好」「感谢您抽时间」），不把多个候选塞进一句（「是A、B还是C」）——候选方向放进 reason。
- reason：≤15 字的要点，关键词用顿号分隔，不带「方向：」「已明确：」之类前缀。todo/new 尽量都给（自明的问题可为空），已有 reason 的条目保留或更新、不要清空。
- todo/new 的 reason 只写维度或候选类型（如「时间点、预算量级」「CTO/销售VP」），不编造具体数值、日期、人名、合规名——访谈基本信息里真有的才可写。
- 参考风格：text「AI 具体帮你们做什么？」reason「转写/提示/报告」。"""

# 会中重算才有 done 条目：在 base 上追加 done 的 reason 语义与示例
_STYLE_RULE = _STYLE_RULE_BASE + """
- done 的 reason 写「主题：结论」，主题 2-3 字，结论不复述问题（如 text「预算大概多少？」reason「预算：1万元/年，严控」）。"""

_OUTPUT_RULE = """只输出 JSON 对象，形如：
{"items": [
  {"id": "pain", "text": "...", "status": "todo|done|new", "reason": "...", "covered_segments": ["s3"], "corrected_segments": {"s3": "..."}}
]}
规则：
- status 三态：done=已在对话里被回答/覆盖；todo=还没覆盖；new=对话里新冒出、此刻必须问清的点。
- 已有条目保留原 id；全新条目 id 填 null（后端分配）。
- done 必须给 covered_segments（支撑它的 seg_id 列表）；非 done 给空数组。
- 同一件事只要对话里已答过就标 done——哪怕措辞不同、或是在别的条目名下答的；不要为已答过的内容另开新条目。
- 主动从对话里发现新的必问点（status=new），别只打勾覆盖；但每次重算 new 最多 2 条，挑最要紧的。
- items 按建议的发问顺序排列，最该先问的排最前。
- done 必须给 reason（≤15 字结论）。
- 已覆盖的对话原文里若有 ASR 错字/漏字，给出你的纠正版本。
  字段 corrected_segments 形态：{"seg_id": "纠正后文本"}。**仅当与原 text 实质不同时填**，
  没纠正就省略。理由写在 reason 里（≤15 字）。**禁止**改写原文意思，只修字词。
- done 才允许填 corrected_segments；非 done 留空对象 {}。
""" + _STYLE_RULE


# 英文 base：跟报告 bug 同根因——中文 base + 一行 EN directive 扛不住 qwen-plus 在中文
# 语境下的镜像效应（实证：访谈 81588cd5-5d3d-4cbf-a823-bf71d4cdbb2a 首评 9 条全中文）。
# 改用独立英文 base + few-shot JSON 示例，让 LLM 走 in-context 而不是听尾部 directive。
# 共享结构规则（{{}} / status / covered_segments 等语言中立部分）翻译为英文版，保留
# 同样的契约——validate_llm_output 同时认中文/英文版。
_STYLE_RULE_BASE_EN = """
- `text`: a concise, conversational English question — at most ~20 words, one point per question. No honorifics, greetings, thanks, or preamble ("Manager Peng,", "Hello,", "Thanks for your time"). Don't cram multiple alternatives into one question ("Is it A, B, or C?") — put candidate directions in `reason`.
- `reason`: ≤15 words of key points; comma-separated keywords; no prefixes like "Direction:" or "Already clear:". Give `reason` for every item (self-explanatory questions may be brief).
- For todo/new items, `reason` should describe dimension or candidate types (e.g. "timeline, budget range", "CTO / Sales VP"), NOT made-up specifics (numbers, dates, names, compliance regimes) — only write what's actually in the interview's basic info.
- Reference style: `text` "What specifically should the AI help you with?" `reason` "transcription / prompting / reports"."""

_STYLE_RULE_EN = _STYLE_RULE_BASE_EN + """
- For `done` items, `reason` writes "topic: conclusion"; topic 2-3 words; conclusion MUST NOT repeat the question (e.g. `text` "Roughly what budget?" `reason` "Budget: 10K RMB/year, tight control")."""

_OUTPUT_RULE_EN = """Output ONLY a JSON object of this exact shape:
{"items": [
  {"id": "<id or null>", "text": "...", "status": "todo|done|new", "reason": "...", "covered_segments": ["s3"], "corrected_segments": {"s3": "..."}}
]}
Rules:
- status three states: `done` = already answered/covered in the conversation; `todo` = not yet covered; `new` = emerged in the conversation and must be clarified now.
- Keep existing item IDs; brand-new items get `id: null` (backend assigns).
- `done` MUST give `covered_segments` (list of `seg_id`s supporting it); non-`done` items give an empty array.
- Mark `done` whenever the conversation has already answered the substance — even if phrased differently or under another item's name; do not open new items for already-answered content.
- Surface newly-emerged must-ask points (`status=new`), not just tick-covered ones; but each recompute may add at most 2 `new` items, picking the most critical.
- Order items by suggested interview order, most urgent first.
- `done` MUST give a `reason` (≤15 word conclusion).
- For ASR errors / omissions in covered transcript, give your corrected version: field `corrected_segments` shape `{"seg_id": "corrected text"}`. **Only fill when substantively different from the original `text`**; skip if no correction. Rationale goes in `reason` (≤15 words). **Never rewrite the original meaning — only fix words/typos.**
- Only `done` may fill `corrected_segments`; non-`done` leaves `{}`.
""" + _STYLE_RULE_EN


def _escape_xml(text: str) -> str:
    """转义用户输入中的 XML 特殊字符，防标签闭合注入。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_system(template: Template, goal: str | None, output_language: str = "zh_cn") -> str:
    playbook = (template.coaching.playbook or "").strip()
    # 用户 goal 用专属标签隔离 + 转义，防 prompt 注入
    goal_block = (
        f"\n<user_goal>\n{_escape_xml(goal.strip())}\n</user_goal>"
        if goal and goal.strip() else ""
    )
    lang = (output_language or "zh_cn").lower()
    if lang == "en":
        base = (
            f"You are a senior interview coach. You assist a product manager conducting a "
            f"needs-discovery / user interview. The goal has been provided; use it together "
            f"with the must_ask baseline to coach the interviewer in real time on what else "
            f"to ask and what to follow up on.{goal_block}\n\n"
            "You will receive: the full conversation transcript, the current question list, "
            "and the IDs skipped this turn (all wrapped in `<user_*>` tags). Output the "
            "**updated complete list**.\n\n"
            f"{_OUTPUT_RULE_EN}"
        )
        return base + _LANG_DIRECTIVE["en"]
    base = (
        f"你是一位资深访谈教练。{playbook}{goal_block}\n\n"
        "我会给你：整段对话原文、当前问题清单、本次被跳过的 id（均以 <user_*> 标签提供）。\n"
        "请输出【更新后的完整清单】。\n\n"
        f"{_OUTPUT_RULE}"
    )
    return base + _LANG_DIRECTIVE.get(lang, "")


_LANG_DIRECTIVE: dict[str, str] = {
    # zh_cn 是默认 → 无需追加指令；其他语种显式切换。
    "zh_tw": "\n\n## 輸出語言\n請用繁體中文撰寫所有 text、reason 與新條目。標點用全形繁體標點。",
    # EN：base 已是英文（build_system / build_first_batch 按 lang 路由），directive
    # 只补"user inputs 可能中文"提示；不再压"全文英文"——那是中文 base 时代的遗留。
    "en": "\n\n## Output language (English, mandatory)\n"
          "- The `<user_*>` blocks below may contain Chinese text (transcript, project / "
          "interviewee / goal metadata, baseline must-ask). Read them as instructions and "
          "translate mentally; write all `text` and `reason` fields in English.\n"
          "- Output ONLY the JSON object — no explanations, no code-block wrapping.",
}


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
        "请输出更新后的完整清单。"
    )


_FIRST_OUTPUT_RULE = """只输出 JSON 对象，形如：
{"items": [
  {"id": "objective", "text": "...", "status": "todo", "reason": "", "covered_segments": [], "corrected_segments": {}}
]}
规则：
- 结合项目背景、受访者与目标定制每条问题的措辞，贴合这次访谈的具体对象，不要照抄基线原文；
- 与基线条目语义对应的必须沿用基线 id；基线之外的新问题 id 填 null（后端分配）；
- status 一律 todo。
- 按建议的发问顺序输出，共 6-10 条。
""" + _STYLE_RULE_BASE


_FIRST_OUTPUT_RULE_EN = """Output ONLY a JSON object of this exact shape:
{"items": [
  {"id": "<baseline id or null>", "text": "...", "status": "todo", "reason": "...", "covered_segments": [], "corrected_segments": {}}
]}
Rules:
- status is always `todo` for first-batch (no transcript yet).
- Each baseline must_ask entry MUST appear once in your output with the same `id` (customize its `text` to fit this interview's project / interviewee / goal — do NOT copy the baseline's Chinese wording verbatim).
- Items semantically not in the baseline may use `id: null` (the backend assigns the id).
- Order the items by suggested interview order, 6-10 items total.
""" + _STYLE_RULE_BASE_EN


def build_first_batch(template: Template, session: Session, output_language: str = "zh_cn") -> tuple[str, str]:
    """首评 prompt：访谈尚未开始，据 base_info/goal + 模板基线生成第一批问题。

    输出契约与重算同形（validate_llm_output 直接可用），区别仅在：无对话依据、
    id 尽量沿用基线、全部 todo、按发问顺序排列。

    EN 模式：英文 base + JSON few-shot 示例，让 LLM 走 in-context 而不是听尾部 directive。
    """
    goal = (session.goal or "").strip()
    goal_block = (
        f"\n<user_goal>\n{_escape_xml(goal)}\n</user_goal>" if goal else ""
    )
    base = json.dumps(session.base_info or {}, ensure_ascii=False)
    baseline = json.dumps(
        [{"id": m.id, "text": m.text} for m in template.coaching.must_ask],
        ensure_ascii=False,
    )
    lang = (output_language or "zh_cn").lower()
    if lang == "en":
        system = (
            "You are a senior interview coach. You assist a product manager conducting a "
            "needs-discovery / user interview. The goal has been provided; use it together "
            f"with the must_ask baseline to coach the interviewer in real time on what else "
            f"to ask and what to follow up on.{goal_block}\n\n"
            "The interview has not started yet (no transcript). You will receive: the "
            "interview's basic info and the template's baseline must-ask list (both wrapped "
            "in `<user_*>` tags). Output the **opening batch of questions** tailored to this "
            "specific interview.\n\n"
            f"{_FIRST_OUTPUT_RULE_EN}\n\n"
            "## Example (output shape and English style)\n"
            "Input baseline (Chinese):\n"
            "[{\"id\": \"objective\", \"text\": \"对方真正想达成什么（动机/目标）\"}, "
            "{\"id\": \"pain\", \"text\": \"痛点 / 未满足需求\"}]\n"
            "Expected output (English, customized to a hypothetical AI-tool-for-Xinnan-pre-sales interview):\n"
            "{\"items\": [\n"
            "  {\"id\": \"objective\", \"text\": \"What does Xinnan's pre-sales team most want the new tool to achieve?\", \"status\": \"todo\", \"reason\": \"core motivation, business goal\", \"covered_segments\": [], \"corrected_segments\": {}},\n"
            "  {\"id\": \"pain\", \"text\": \"In current pre-sales conversations, which step is the most time-consuming or error-prone?\", \"status\": \"todo\", \"reason\": \"workflow bottleneck, repetition, information loss\", \"covered_segments\": [], \"corrected_segments\": {}}\n"
            "]}\n"
        )
        system += _LANG_DIRECTIVE["en"]
    else:
        playbook = (template.coaching.playbook or "").strip()
        system = (
            f"你是一位资深访谈教练。{playbook}{goal_block}\n\n"
            "本次访谈尚未开始（没有对话记录）。我会给你：访谈基本信息、"
            "模板基线必问清单（均以 <user_*> 标签提供）。\n"
            "请输出【开场该问的第一批问题清单】。\n\n"
            f"{_FIRST_OUTPUT_RULE}"
        )
        system += _LANG_DIRECTIVE.get(lang, "")
    user = (
        f"<user_base_info>\n{_escape_xml(base)}\n</user_base_info>\n\n"
        f"<user_baseline>\n{_escape_xml(baseline)}\n</user_baseline>\n\n"
        "请输出第一批访谈问题清单。"
    )
    return system, user

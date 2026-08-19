"""报告生成：照模板 Markdown 骨架，transcript 喂 LLM 填报告。

报告是 Markdown 文本 → 用 get_llm().chat_text。
懒加载：GET /report 首次请求时生成 + 落库。

所有 DB 操作走 ReportRepository。
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import re
from typing import Awaitable, Callable, Optional

import bleach

from app.adapters.llm.base import LLMError
from app.adapters.llm.factory import get_llm
from app.core.config_store import get_config_store
from app.domain.session import TranscriptSegment
from app.persistence.repositories.interview import interview_repo
from app.persistence.repositories.report import report_repo
from app.services.reports.skill_renderer import render_skills
from app.services.sessions.state import SessionState
from app.services.template.loader import get_template

logger = logging.getLogger(__name__)

# 骨架里的 {{session.X}}：由后端从 state 预填，再交给 LLM。
# LLM 不该看到这些占位符（曾因 transcript 里没有 start_time / end_time 而原样留着）。
_SESSION_PLACEHOLDER_RE = re.compile(r"\{\{session\.([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def _transcript_signature(transcript: list[TranscriptSegment]) -> str:
    """transcript 指纹：sha256[:16] 文本+seg_id 排序后哈希。

    transcript 任何段变化（新增/修改/删除）→ 签名变 → 报告缓存失效 → 重生。
    """
    payload = json.dumps(
        [{"seg_id": s.seg_id, "text": s.text, "corrected_text": s.corrected_text} for s in transcript],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _prefill_session_placeholders(doc: str, state: SessionState) -> str:
    bi = state.session.base_info or {}

    def _resolve(name: str) -> str:
        if name in bi and bi[name] not in (None, ""):
            return str(bi[name])
        # base_info 没填时，start/end_time 从 Session 字段取（setup.extract_to 默认含这俩）
        if name == "start_time" and state.session.started_at is not None:
            return state.session.started_at.strftime("%Y-%m-%d %H:%M")
        if name == "end_time" and state.session.ended_at is not None:
            return state.session.ended_at.strftime("%Y-%m-%d %H:%M")
        return ""

    return _SESSION_PLACEHOLDER_RE.sub(lambda m: _resolve(m.group(1)), doc)


_REPORT_SYSTEM = """你是访谈报告撰写助手。照给定的 Markdown 骨架填一份报告。

## 关键规则
- 骨架里每一处 `{{ ... }}`（不含 `{{session.X}}` 与 `{{skill: ...}}`）都是**占位符**：
  - 把它**整块替换**为从【对话原文】抽取的内容（一段话或列表，贴合提示语义）。
  - **删掉 `{{` `}}` 包装**和里面的提示文字，输出里**不允许**出现 `{{` 或 `}}`。
  - 【对话原文】里确实没有可填的内容时，写一句「本次访谈未提及」之类的明确说明，
    **不允许**留空或只留骨架里的标签文字——空章节在报告里看起来像生成失败。
    例：骨架 `- 客户 / 行业：{{ 客户与行业标签 }}` 无内容时输出
    `- 客户 / 行业：本次访谈未提及`，而不是 `- 客户 / 行业：`。
- `{{session.X}}` 已被系统填好，**原样保留**。
- `{{skill: ...}}` 是技能标记，**原样保留**（其内部 `{{ }}` 不要动）。

## 其它
- 保持标题层级与章节顺序，不要增删章节。
- 只输出填好的 Markdown，不要加解释或代码块包裹。"""

# 报告输出语种指令：默认 zh_cn 不追加（与现有报告形态一致），其他语种显式切换。
# 设计要点（en directive）：
# 1. 强约束全文英文（含 heading / bullet label / 占位符填充）。
# 2. 显式告知 LLM「忽略 base prompt 的中文结构约束」——这是 qwen-plus 在中文 base
#    + 中文转写场景下默认输出中文的根因；不加这一句 directive 会被镜像行为压过。
# 3. 提供 fallback 短语，与 _fill_dangling_labels 的兜底严丝合缝。
# 4. 保留通用规则（{{session.X}} 预填、{{skill: ...}} 标记、章节层级、Markdown 输出形态）。
_REPORT_LANG_INSTRUCTION: dict[str, str] = {
    "zh_cn": "",
    "zh_tw": "\n\n## 輸出語言\n報告正文請用繁體中文撰寫（標點用全形繁體標點）。"
          "Markdown 結構（`#` / `-` / 列表）保持不變。空章節兜底用「本次訪談未提及」。",
    "en": "\n\n## Output language (English, mandatory)\n"
          "- Write the ENTIRE report body in English — including all section headings, "
          "bullet labels, and every fill-in for `{{ ... }}` placeholders.\n"
          "- Even if the conversation transcript and the user-provided project / "
          "interviewee / goal metadata are in Chinese, do NOT copy Chinese text. "
          "Synthesize the user's points into English prose, and translate metadata "
          "into English when you restate them.\n"
          "- `{{session.X}}` placeholders are pre-filled by the system — keep them "
          "verbatim. `{{skill: ...}}` tags are invocation points — keep them verbatim "
          "(do not touch the inner `{{ }}`).\n"
          "- If a section has no content in the transcript, render the label followed "
          "by `Not mentioned in this interview.` (in English). Do not leave the "
          "placeholder, do not leave the section empty.\n"
          "- Keep the heading hierarchy and section order from the skeleton; do NOT add "
          "or remove sections. Output only the filled Markdown — no explanations or "
          "code-block wrapping.\n"
          "- **Ignore the Chinese structural guidance in the base system prompt; the "
          "English rules above are the only structural rules to follow for English "
          "output.** Treat the base prompt's labels and example phrasings as "
          "language-neutral scaffolding only.",
}


def _report_system(output_language: str) -> str:
    """根据 llm.output_language 拼出报告 system prompt。"""
    return _REPORT_SYSTEM + _REPORT_LANG_INSTRUCTION.get(
        (output_language or "zh_cn").lower(), ""
    )

# P3-9: 报告渲染为 HTML 前的白名单。strip=True 移除非白名单标签（含属性）。
_ALLOWED_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "ul", "ol", "li",
    "strong", "em", "b", "i", "code", "pre",
    "a", "blockquote", "table", "thead", "tbody", "tr", "th", "td",
]
_ALLOWED_ATTRS = {"a": ["href", "title"], "code": ["class"]}


# 兜底：LLM 偶尔会在 `{{ ... }}` 里填内容但忘了删 `{{`/`}}` 包装。
# 保留 `{{skill: ...}}`（标记技能调用），其它整块删掉。
# 匹配 `{{` 后面非 `skill:` 开头、非 `}` 字符、再到 `}}`。
_ORPHAN_PLACEHOLDER_RE = re.compile(r"\{\{(?!skill:)[^}]*\}\}", re.DOTALL)


def _strip_orphan_placeholders(md: str) -> str:
    """LLM 没填的占位符整块清除。"""
    matches = list(_ORPHAN_PLACEHOLDER_RE.finditer(md))
    if not matches:
        return md
    logger.warning("LLM 残留 %d 个未填占位符，已自动清除", len(matches))
    out = md
    for m in reversed(matches):
        out = out[: m.start()] + out[m.end() :]
    return out


# 「- 标签：」行尾（标签后无内容）。合法形态是同行跟内容或下一行缩进子条目。
_DANGLING_LABEL_RE = re.compile(r"^(\s*[-*]\s*.*[:：])\s*$")

# 兜底短语按语种切：与 _report_system 中的 directive 严丝合缝。
# 避免 LLM 输出正确英文报告后被后处理注入中文（之前硬编码「本次访谈未提及」时的隐性 bug）。
_FALLBACK_BY_LANG: dict[str, str] = {
    "zh_cn": "本次访谈未提及",
    "zh_tw": "本次訪談未提及",
    "en": "Not mentioned in this interview.",
}


def _fill_dangling_labels(md: str, language: str = "zh_cn") -> str:
    """悬空标签兜底：LLM 无内容可填时偶尔只留「- 标签：」空行，机械补上说明。

    提示词已有「须写未提及」规则，但 LLM 执行不稳定——这里是确定性兜底，
    保证报告里不会出现看起来像生成失败的空章节。

    language 参数决定兜底短语：默认 zh_cn（与改前一致），en/zh_tw 显式切换。
    未知语种回退到 zh_cn 短语（保守）。
    """
    fallback = _FALLBACK_BY_LANG.get((language or "zh_cn").lower(), _FALLBACK_BY_LANG["zh_cn"])
    lines = md.splitlines()
    filled = 0
    for i, ln in enumerate(lines):
        m = _DANGLING_LABEL_RE.match(ln)
        if not m:
            continue
        has_sub = i + 1 < len(lines) and lines[i + 1][:1] in (" ", "\t")
        if not has_sub:
            lines[i] = m.group(1) + " " + fallback
            filled += 1
    if filled:
        logger.warning("报告有 %d 个空章节标签，已补兜底短语（语种=%s）", filled, language)
    return "\n".join(lines)


def sanitize_report_markdown(md: str) -> str:
    """消毒 Markdown：剔除非白名单 HTML 标签（strip=True），保留 Markdown 语义符号。

    bleach 默认把 `>` 转义成 `&gt;`、`<` 转义成 `&lt;`（HTML 语义）。
    这会让 Markdown 引用块写成 `&gt;`、文本里的 `<` 写成 `&lt;`，看起来像 bug。
    报告本就是 Markdown 源（前端 textContent 渲染、导出给 .md 文件），
    在 Markdown 上下文里这些是普通字符——剥完标签后用 html.unescape 还原。
    又因为前端用 textContent 而 HTML 导出走 `markdown.markdown` 重新渲染，
    这里还原 `>` / `<` 不会引入 XSS。
    """
    cleaned = bleach.clean(md, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)
    return html.unescape(cleaned)


def _build_user(state: SessionState, template) -> str:
    def _seg_text(s: TranscriptSegment) -> str:
        return s.corrected_text.strip() or s.text

    transcript = "\n".join(f"[{s.seg_id}] {_seg_text(s)}" for s in state.transcript) or "（无对话）"
    bi = state.session.base_info or {}
    doc = _prefill_session_placeholders(template.report.doc, state)
    return (
        f"【报告骨架】\n{doc}\n\n"
        f"【会话基础信息】\n项目：{bi.get('project', '')}　受访者：{bi.get('interviewee', '')}"
        f"　目标：{state.session.goal or ''}\n\n"
        f"【对话原文】\n{transcript}\n\n"
        "请照骨架填报告。"
    )


async def generate_report(state: SessionState, template, language: str) -> str:
    """LLM 照骨架填报告 → Markdown（已消毒）。

    language 由调用方（get_or_generate）一次性从 ConfigStore 读出并透传——
    避免 get_or_generate 与 generate_report 之间 read-then-read 的窗口被 admin
    翻语种污染（之前会出现「cache 标 post-flip、content pre-flip EN」的 race，
    报告内容跟缓存标签不一致，下次请求继续按新语种命中失配的内容）。
    """
    llm = get_llm()
    md = await llm.chat_text(_report_system(language), _build_user(state, template))
    md = _fill_dangling_labels(_strip_orphan_placeholders(md.strip()), language=language)
    return sanitize_report_markdown(md)


# single-flight：生成耗时 ~10s，窗口内同一 session 的重复请求只放一个进 LLM，
# 后到的等锁后命中缓存。锁是进程内的；多进程/多实例部署需换 DB 行锁或分布式锁。
_gen_locks: dict[str, asyncio.Lock] = {}


def _cache_hit(rec, sig: str, language: str) -> bool:
    """报告缓存有效：ready + 有内容 + 指纹匹配 + 语种匹配。

    旧行 transcript_signature 为空 → 视为失效；output_language 为空（迁移前老行）
    同样视为未标 → 失效。管理员改 llm.output_language 后，存量的旧语种报告不会再
    一直命中——避免「中文报告永远返回」的隐性 bug。
    """
    return bool(
        rec
        and rec.status == "ready"
        and rec.content_md
        and rec.transcript_signature
        and rec.transcript_signature == sig
        and (rec.output_language or "") == language
    )


async def get_or_generate(
    session_id: str,
    on_ready: Optional[Callable[[str], Awaitable[None]]] = None,
) -> tuple[str, str]:
    """返回 (status, content_md)。

    缓存命中：report ready 且 transcript 指纹未变 → 直接返回旧内容。
    缓存失效：未生成 / 上次失败 / transcript 变了 → 调 LLM 重生 + 落库。

    on_ready：每次报告状态落定（成功 ready / 失败 failed）后调用一次；缓存命中
    也算「状态落定」。回调异常被吞掉、不传播——推送失败不应影响 GET 返回。
    预检失败（session/template 缺失）不触发回调：此时根本无报告可言。
    """
    # 1. 先加载 state（transcript 指纹计算需要它）+ 缓存查询
    state = await interview_repo.get_state_auto(session_id)
    if state is None:
        raise ValueError(f"session not found: {session_id}")
    current_sig = _transcript_signature(state.transcript)
    # 一次性读 llm.output_language：本次请求全程共用一个值（缓存命中判定 / 调 LLM
    # / 落库标签）。彻底消除之前「cache 标 post-flip、content pre-flip」的 race。
    language = (
        get_config_store().get_sync("llm.output_language") or "zh_cn"
    ).strip().lower() or "zh_cn"

    rec = await report_repo.get_by_interview_auto(session_id)
    if _cache_hit(rec, current_sig, language):
        await _fire_on_ready(on_ready, session_id, "ready")
        return ("ready", rec.content_md)

    # 2. single-flight：拿锁后双重检查，等锁期间别人可能已生成完并落库
    lock = _gen_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        rec = await report_repo.get_by_interview_auto(session_id)
        if _cache_hit(rec, current_sig, language):
            await _fire_on_ready(on_ready, session_id, "ready")
            return ("ready", rec.content_md)

        # 3. 加载模板
        template = get_template(state.session.template_id)
        if template is None:
            raise ValueError(f"template not found: {state.session.template_id}")

        # 4. 生成
        try:
            md = await generate_report(state, template, language)
            md = await render_skills(md)
            status = "ready"
        except LLMError as e:
            logger.warning("报告生成失败：session=%s 原因=%s", session_id, e)
            md, status = "", "failed"

        # 5. 落库（upsert + 更新指纹 + 语种）
        await report_repo.upsert_auto(
            session_id, md, status,
            transcript_signature=current_sig, output_language=language,
        )

        await _fire_on_ready(on_ready, session_id, status)
        return (status, md)


async def _fire_on_ready(
    on_ready: Optional[Callable[[str], Awaitable[None]]],
    session_id: str,
    status: str,
) -> None:
    """on_ready 包装：吞掉回调异常，避免推送失败影响 GET 返回。"""
    if on_ready is None:
        return
    try:
        await on_ready(status)
    except Exception:  # noqa: BLE001
        logger.exception("report.ready 推送失败：session=%s", session_id)

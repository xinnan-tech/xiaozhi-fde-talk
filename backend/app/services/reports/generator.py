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
# Bug 修：原 zh_tw 一直为空，繁體中文用戶看到的是簡體報告。
_REPORT_LANG_INSTRUCTION: dict[str, str] = {
    "zh_cn": "",
    "zh_tw": "\n\n## 輸出語言\n報告正文請用繁體中文撰寫（標點用全形繁體標點）。"
          "Markdown 結構（`#` / `-` / 列表）保持不變。",
    "en": "\n\n## Output language\nWrite the entire report body in English. "
          "Keep the Markdown structure (`#`/`-`/lists) as in the skeleton.",
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


def _fill_dangling_labels(md: str) -> str:
    """悬空标签兜底：LLM 无内容可填时偶尔只留「- 标签：」空行，机械补上说明。

    提示词已有「须写未提及」规则，但 LLM 执行不稳定——这里是确定性兜底，
    保证报告里不会出现看起来像生成失败的空章节。
    """
    lines = md.splitlines()
    filled = 0
    for i, ln in enumerate(lines):
        m = _DANGLING_LABEL_RE.match(ln)
        if not m:
            continue
        has_sub = i + 1 < len(lines) and lines[i + 1][:1] in (" ", "\t")
        if not has_sub:
            lines[i] = m.group(1) + " 本次访谈未提及"
            filled += 1
    if filled:
        logger.warning("报告有 %d 个空章节标签，已补「本次访谈未提及」", filled)
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


async def generate_report(state: SessionState, template) -> str:
    """LLM 照骨架填报告 → Markdown（已消毒）。

    llm.output_language 现读 ConfigStore：每次报告生成时读，不依赖调用方传入——
    避免依赖陈旧缓存（管理员在 admin 页改语种后，旧 session 立即生效）。
    """
    llm = get_llm()
    language = (
        get_config_store().get_sync("llm.output_language") or "zh_cn"
    ).strip().lower() or "zh_cn"
    md = await llm.chat_text(_report_system(language), _build_user(state, template))
    md = _fill_dangling_labels(_strip_orphan_placeholders(md.strip()))
    return sanitize_report_markdown(md)


# single-flight：生成耗时 ~10s，窗口内同一 session 的重复请求只放一个进 LLM，
# 后到的等锁后命中缓存。锁是进程内的；多进程/多实例部署需换 DB 行锁或分布式锁。
_gen_locks: dict[str, asyncio.Lock] = {}


def _cache_hit(rec, sig: str) -> bool:
    """报告缓存有效：ready + 有内容 + 指纹匹配（旧行指纹为空 → 视为失效，重生一次后填上）。"""
    return bool(
        rec
        and rec.status == "ready"
        and rec.content_md
        and rec.transcript_signature
        and rec.transcript_signature == sig
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

    rec = await report_repo.get_by_interview_auto(session_id)
    if _cache_hit(rec, current_sig):
        await _fire_on_ready(on_ready, session_id, "ready")
        return ("ready", rec.content_md)

    # 2. single-flight：拿锁后双重检查，等锁期间别人可能已生成完并落库
    lock = _gen_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        rec = await report_repo.get_by_interview_auto(session_id)
        if _cache_hit(rec, current_sig):
            await _fire_on_ready(on_ready, session_id, "ready")
            return ("ready", rec.content_md)

        # 3. 加载模板
        template = get_template(state.session.template_id)
        if template is None:
            raise ValueError(f"template not found: {state.session.template_id}")

        # 4. 生成
        try:
            md = await generate_report(state, template)
            md = await render_skills(md)
            status = "ready"
        except LLMError as e:
            logger.warning("报告生成失败：session=%s 原因=%s", session_id, e)
            md, status = "", "failed"

        # 5. 落库（upsert + 更新指纹）
        await report_repo.upsert_auto(session_id, md, status, transcript_signature=current_sig)

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

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
from app.core.i18n.pivot import _with_lang_fallback
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


# 单一英文 base 报告 prompt——所有语种共用。设计要点：
# 1. 中文 base + 中文骨架 + 中文转写三层叠加下 qwen-plus 会**镜像中文**完全忽略
#    EN directive（实测案例见 ce645969-bfb4-47a4-b327-89502a44f6f7，全 842 字符中文
#    报告包括中文 fallback「本次访谈未提及」都是 LLM 抄 base 示例，不是后处理注入）。
#    改用**单一英文 base** 跨所有语种——EN base 让 LLM 不再被中文镜像效应拉回去。
# 2. 两步式：先翻译骨架（heading / bullet label → {lang_native}），再填内容。
#    示例演示两步流程而非具体语言翻译结果——避免示例语言与目标语种冲突。
# 3. 占位符规则（`{{ ... }}` 删除、`{{session.X}}` 与 `{{skill: ...}}` 豁免）正面重申
#    ——这些是**语言中立**的结构规则，不能因 base 语言是英文而弱化。
# 4. zh_cn/zh_tw 也走同一段 base——MVP 验证 EN base + 中文输出指令产出 CN=790（比中文
#    base + 中文指令 CN=667 字数还多 18%），证明母语写作质量不降反升。
# 5. 4 个 format 占位符：{lang_native}/{lang_english}/{lang_bcp47}/{fallback_phrase}，
#    运行时从 _LANG_META + _FALLBACK_BY_LANG 注入。
_REPORT_SYSTEM = """You are an interview report-writing assistant.

## Task (two steps, do both)
**Step 1 — Skeleton translation.** The skeleton in the user message is written in Chinese. Mentally translate each skeleton heading and bullet label into {lang_native} ({lang_english}, {lang_bcp47}). Do NOT copy the Chinese headings verbatim into your output.
**Step 2 — Content fill.** Fill the ({lang_native}-translated) skeleton with content drawn from the conversation transcript, in {lang_native}.

## Key rules (apply during Step 2)
- Each `{{ ... }}` in the skeleton (excluding `{{session.X}}` and `{{skill: ...}}`) is a **placeholder**:
  - Replace the entire `{{ ... }}` block with {lang_native} content drawn from the transcript.
  - Delete the `{{` and `}}` wrappers AND any Chinese prompt text inside. The output MUST NOT contain `{{` or `}}`.
  - When the transcript genuinely has no content, write {fallback_phrase}. Do NOT leave an empty bullet or only the placeholder label.
- `{{session.X}}` is pre-filled by the system — **keep these values verbatim** (do not translate the pre-filled values; they are session metadata already committed by the system).
- `{{skill: ...}}` is a skill invocation marker — **keep verbatim** (do not touch the inner `{{ }}`).

## Example (two-step process, language-agnostic)
Input skeleton (Chinese):
```
## 背景与目的
{{ 项目背景、为什么做、目标 }}
```
Process: translate heading `## 背景与目的` to your output language (e.g. `## Background & Goals` if English; `## Bối cảnh & Mục tiêu` if Vietnamese; `## 背景與目的` if Traditional Chinese), then replace `{{ 项目背景、为什么做、目标 }}` with content drawn from the transcript, in your output language.

## Output language ({lang_native}, mandatory)
- Write the ENTIRE output in {lang_native} ({lang_english}, {lang_bcp47}) — including all section headings, bullet labels, and every fill-in for `{{ ... }}` placeholders.
- The transcript is in Chinese and the session metadata values pre-filled into `{{session.X}}` may also be in Chinese. Translate them into {lang_native} when you RESTATE them in the report's prose. (Keep the literal pre-filled `{{session.X}}` markers as the system has resolved them; only translate the metadata when you paraphrase it elsewhere.)
- Two categories of placeholders are EXEMPT from wrapper deletion — keep them VERBATIM, including their `{{`/`}}` markers: (1) `{{session.X}}` placeholders already pre-filled by the system, and (2) `{{skill: <id>, inputs: <json>}}` invocation points.

## Other
- Preserve the heading hierarchy and section order from the translated skeleton. Do not add or remove sections.
- Output only the filled Markdown — no explanations or code-block wrapping."""


def _report_system(output_language: str) -> str:
    """拼出报告 system prompt——单一英文 base + 参数化语言指令注入。

    所有语种共用同一段 _REPORT_SYSTEM：{lang_native}/{lang_english}/{lang_bcp47}/
    {fallback_phrase} 4 个占位符运行时从 _LANG_META + _FALLBACK_BY_LANG 注入。
    """
    lang = (output_language or "zh_cn").lower()
    meta = get_lang_meta(lang)
    phrases = derived_fallback_phrases()
    return _REPORT_SYSTEM.format(
        lang_native=meta.native_name,
        lang_english=meta.english_name,
        lang_bcp47=meta.bcp47,
        fallback_phrase=phrases.get(lang, phrases["en"]),
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


# 兜底：LLM 偶尔会在 `{{ ... }}` 里填内容但忘了删 `{{`/`}}` 包装，整块清除。
# 保留两类 EXEMPT：`{{skill: ...}}`（技能调用点，系统后处理要识别）+ `{{session.X}}`
# （会话元数据占位符，与 base skeleton 的 _prefill_session_placeholders 同形态——
# 如果误以为是 orphan 删掉，会丢项目名/受访者/时间等关键元数据，且前端无法再补回）。
# 匹配 `{{` 后面既非 `skill:` 也非 `session.` 开头的占位符。
_ORPHAN_PLACEHOLDER_RE = re.compile(r"\{\{(?!(?:skill:|session\.))[^}]*\}\}", re.DOTALL)


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
# 从 app.core.i18n.lang_meta 派生：单一真源 _LANG_META，加语种只改一处。
from app.core.i18n.lang_meta import (
    _LANG_META,
    derived_fallback_phrases,
    get_lang_meta,
)

_FALLBACK_BY_LANG: dict[str, str] = derived_fallback_phrases()


# 跨 dict 不变量：兜底短语键集合必须等于 _LANG_META 键集合——任一缺都意味着派生
# 源漂移（fallback_phrase 已并入 LangMeta，键集合必须 1:1），import 期 fail-fast
# 比单测 delayed-feedback 更早暴露。
assert set(_FALLBACK_BY_LANG) == set(_LANG_META), (
    "兜底短语键集合必须等于 _LANG_META 键集合："
    f"fallback={set(_FALLBACK_BY_LANG)} vs lang_meta={set(_LANG_META)}"
)


def _fill_dangling_labels(md: str, language: str = "en") -> str:
    """悬空标签兜底：LLM 无内容可填时偶尔只留「- 标签：」空行，机械补上说明。

    提示词已有「须写未提及」规则，但 LLM 执行不稳定——这里是确定性兜底，
    保证报告里不会出现看起来像生成失败的空章节。

    language 参数决定兜底短语：默认 en（与 get_lang_meta 未知 lang fallback 一致，
    避免英文报告被回退注入「本次访谈未提及」中文短语的隐性 bug）。
    """
    fallback = _FALLBACK_BY_LANG.get((language or "en").lower(), _FALLBACK_BY_LANG["en"])
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

    pivot：LLM 输出脚本与 language 不符 → 切 fallback_lang（en）重试一次，
    effective_lang 传给 _fill_dangling_labels 决定兜底短语（pivot 后 zh_cn
    请求变成 en 输出，兜底短语也得跟着 en）。
    """
    llm = get_llm()

    async def _call(system: str, user: str) -> str:
        return await llm.chat_text(system, user)

    md, effective_lang = await _with_lang_fallback(
        _call, _report_system(language), _report_system, _build_user(state, template), language,
    )
    md = _fill_dangling_labels(_strip_orphan_placeholders(md.strip()), language=effective_lang)
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

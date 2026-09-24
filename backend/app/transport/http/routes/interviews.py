"""访谈路由。"""
from __future__ import annotations

import asyncio as _asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from app.core.config_store import get_config_store
from app.core.i18n import Keys, current_locale, t
from app.core.i18n.errors import I18nError, LLMContextOverflowError
from app.core.i18n.extract_prompts import build_extract_system
from app.core.i18n.ocr_prompts import OCR_PROMPT
from app.core.retry import RateLimiter
from app.domain.auth import CurrentUser
from app.domain.session import SessionStatus
from app.domain.template import Template
from app.services.coaching.engine import TERMINAL_SESSION_STATUSES
from app.services.coaching.first_batch import generate_first_batch
from app.services.sessions.manager import manager
from app.services.sessions.runtime import registry
from app.services.sessions.state import SessionState
from app.services.template.loader import resolve_template
from app.transport.http.dependencies import get_current_user
from app.transport.http.schemas import (
    CanvasListResponse,
    CreateInterviewRequest,
    CreateKeyboardNoteRequest,
    DeleteCanvasRequest,
    DeleteCanvasResponse,
    ExtractRequest,
    ExtractResponse,
    InterviewStatisticsResponse,
    KeyboardListResponse,
    KeyboardNoteResponse,
    OCRRequest,
    OCRResponse,
    SaveCanvasRequest,
    SaveCanvasResponse,
    UpdateInterviewRequest,
    _validate_base_info_size,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interviews")

# LLM 转发路由共用一份按 user_id 的配额桶：extract / first-batch / ocr 三个
# 路由各自走 LLM，单用户额度打通算更省成本（绕开「分桶稀释成 60/h」的绕过路径）。
# capacity=20、refill_per_hour=20 等价令牌桶上限 20/h。Depends(get_current_user)
# 先验 token，再按 user_id 抢令牌——没登录的用户在被 401 挡掉前不会消耗桶。
_llm_user_limiter = RateLimiter(capacity=20, refill_per_hour=20)

# OCR 后台 task 强引用集：event loop 只持弱引用,长跑 task(5 轮 × 30s ≈
# 2 分钟)在 memory pressure 下会被 GC,DB 行卡 pending 永远等不到结果。
# add_done_callback 在 task 结束自动从集合移除,不泄漏。
_ocr_bg_tasks: set["_asyncio.Task"] = set()


def _reset_for_test() -> None:
    """清空 LLM 用户配额桶。env 守门，prod 误调会清掉所有封禁桶。

    与 auth.py 五桶同款约定——模块级 RateLimiter 跨用例持续累加，不暴露 reset
    的话测试要么 sleep 等令牌再生（慢）、要么依赖运气。生产误调会清掉所有
    封禁桶，故显式 env 守门——只放行 dev/test，禁止 prod。
    """
    from app.core.settings import get_settings

    if get_settings().env not in ("test", "dev"):
        return
    _llm_user_limiter._buckets.clear()


_STATUS_TYPE = {
    "created": "info",
    "setting_up": "info",
    "in_progress": "info",
    "suspended": "warning",
    "ended": "success",
    "extracting": "info",
    "done": "success",
}


def _utc_isoformat(value: datetime | None) -> str | None:
    """将数据库时间按 UTC 明确输出，供客户端安全本地化显示。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _is_supported_image_format(image_bytes: bytes) -> bool:
    """按 magic bytes 嗅探图片格式，仅接受 JPEG / PNG / BMP。

    客户端 OCRRequest 不传文件名（extra=forbid），扩展名校验不适用；
    引入 PIL 仅做 sniff 太重。百度 OCR 等 provider 对 WEBP / GIF / TIFF /
    HEIC 等格式支持不一致或拒收，提前在路由层拒掉非白名单字节，避免
    垃圾数据送上游再回错误。
    """
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return True
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if image_bytes.startswith(b"BM"):
        return True
    return False


def _resolve_interviewee(base_info: dict, tpl: Optional[Template]) -> str:
    """从 base_info 解析受访者展示字段。

    优先取名为 `interviewee` 的键（与前端展示约定一致）；空串 / 纯空白 / 缺
    失则启发式回落：按模板 `base_fields` 声明顺序选首个 type=text 且值非空的
    字段。非 text 字段（datetime / duration / select / number / textarea 等）
    均不参与。这样自定义模板不必死磕"必须叫 interviewee"——任何能识别人物的字段
    都能上首页卡片。模板缺失时返回空串，保持现有前端 — fallback。
    """
    direct = base_info.get("interviewee")
    if direct and str(direct).strip():
        return str(direct)
    if tpl is None:
        return ""
    for f in tpl.session.base_fields:
        if f.type != "text":
            continue
        v = base_info.get(f.key)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        return str(v)
    return ""


def _session_summary(rec, tpl) -> dict:
    """ORM InterviewRecord + Template → summary dict（含派生计数与展示字段）。

    字段集合见 Task A3 描述。
    """
    base_info = rec.base_info or {}
    items = rec.coaching_items or []
    ignored_ids = set(rec.ignored_ids or [])

    pending_count = sum(1 for it in items if it.get("status") in ("todo", "new"))
    covered_count = sum(1 for it in items if it.get("status") == "done")
    coverage_index = rec.coverage_index or {}
    asked_count = sum(
        1 for it in items
        if it.get("status") == "done" and len(coverage_index.get(it["id"], [])) > 0
    )

    return {
        "id": rec.id,
        "template_id": rec.template_id,
        "template_version": rec.template_version,
        "template_icon_url": tpl.icon_url if tpl else "",
        "template_snapshot": rec.template_snapshot,
        "status": rec.status,
        "status_type": _STATUS_TYPE.get(rec.status, "info"),
        "base_info": base_info,
        "title": base_info.get("title") or t(Keys.HTTP_SESSION_TITLE_DEFAULT, locale=current_locale()),
        "interviewee": _resolve_interviewee(base_info, tpl),
        "type": tpl.name if tpl else "",
        "recent_time": _utc_isoformat(max(
            filter(None, [rec.created_at, rec.started_at, rec.ended_at])
        )) if any([rec.created_at, rec.started_at, rec.ended_at]) else None,
        "goal": rec.goal,
        "pending_count": pending_count,
        "covered_count": covered_count,
        "asked_count": asked_count,
        "ignored_count": len(ignored_ids),
        "total_count": len(items),
        "created_at": _utc_isoformat(rec.created_at),
        "started_at": _utc_isoformat(rec.started_at),
        "ended_at": _utc_isoformat(rec.ended_at),
    }


async def _summary_from_session_id(session_id: str) -> dict:
    """根据 session_id 取 ORM + 模板，返回 _session_summary dict。

    找不到会话则抛 404（与路由层语义一致）。
    """
    from app.persistence.db import SessionLocal
    from app.persistence.models import InterviewRecord
    from app.services.template.loader import resolve_template
    async with SessionLocal() as db:
        rec = await db.get(InterviewRecord, session_id)
        if rec is None:
            raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
        tpl = resolve_template(rec.template_id, rec.template_snapshot)
        return _session_summary(rec, tpl)


def _state_detail(state) -> dict:
    from app.services.template.loader import resolve_template
    s = state.session
    # 模板字段定义（快照优先）：运行页据此渲染 base_info 的 label/控件，
    # 不再写死固定键；模板删了也不怕——快照随访谈存
    tpl = resolve_template(s.template_id, s.template_snapshot)
    base_info = s.base_info or {}
    return {
        "id": s.id,
        "template_id": s.template_id,
        "template_version": s.template_version,
        "template_snapshot": s.template_snapshot,
        "status": s.status.value,
        # 与列表接口对齐：title 顶层字段 = base_info.title，无值时回退到 i18n
        # 默认文案；这样 list / detail 切换不会出现「字段消失 / 值不一致」
        "title": base_info.get("title") or t(Keys.HTTP_SESSION_TITLE_DEFAULT, locale=current_locale()),
        "template_fields": [
            {"key": f.key, "label": f.label, "type": f.type}
            for f in tpl.session.base_fields
        ] if tpl else [],
        "base_info": base_info,
        "goal": s.goal,
        "first_batch_generated": s.first_batch_generated,
        "consumed_seq": s.consumed_seq,
        "created_at": _utc_isoformat(s.created_at),
        "started_at": _utc_isoformat(s.started_at),
        "ended_at": _utc_isoformat(s.ended_at),
        "items": [it.model_dump(mode="json") for it in state.items],
        "skipped_ids": sorted(state.skipped_ids),
        "ignored_ids": sorted(state.ignored_ids),
        "coverage": state.coverage,
        "transcript": [seg.model_dump(mode="json") for seg in state.transcript],
    }


@router.post("")
async def create_interview(
    req: CreateInterviewRequest,
    user: CurrentUser = Depends(get_current_user),
):
    try:
        state = await manager.create(user.user_id, req.template_id, req.base_info, req.goal)
    except KeyError:
        raise I18nError(Keys.HTTP_TEMPLATE_NOT_FOUND, http_status=404)
    return await _summary_from_session_id(state.session.id)


@router.get("")
async def list_interviews(
    status: Optional[str] = Query(
        None,
        description="逗号分隔：created/setting_up/in_progress/suspended/ended/extracting/done",
    ),
    user: CurrentUser = Depends(get_current_user),
):
    statuses: Optional[list[SessionStatus]] = None
    if status:
        try:
            statuses = [
                SessionStatus(s.strip()) for s in status.split(",") if s.strip()
            ]
        except ValueError as e:
            raise I18nError(Keys.HTTP_UNKNOWN_STATUS, http_status=400, value=str(e))
    pairs = await manager.list_summaries_for_user(user.user_id, statuses=statuses)
    return {"items": [_session_summary(rec, tpl) for rec, tpl in pairs]}


@router.get("/statistics", response_model=InterviewStatisticsResponse)
async def interview_statistics(
    user: CurrentUser = Depends(get_current_user),
):
    """首页四张统计卡聚合数字（snake_case keys）。"""
    return await manager.statistics_for_user(user.user_id)


@router.get("/{session_id}")
async def get_interview(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    # 资源隔离：不是本人的访谈一律 404（不泄露存在性）
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    return _state_detail(state)


@router.patch("/{session_id}")
async def update_interview(
    session_id: str,
    req: UpdateInterviewRequest,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    # PATCH 是增量合并：UpdateInterviewRequest 已校验 req.base_info 单字段 / 整体上限，
    # 但合并到 DB 现值后总字节仍可能超 BASE_INFO_TOTAL_MAX_BYTES（先 POST 60KB、
    # 再 PATCH 10KB 增量，多次 PATCH 可无限放大）。
    # route 层对 merged 跑一遍 _validate_base_info_size 是 fast-fail（基于本路由 GET
    # 快照；多数单请求场景足够早返 422）。manager.update 内部还会基于它自己的 GET
    # 快照再校验一次，挡住 route GET 与 manager.update GET 之间的并发 PATCH 累计
    # 放大（见 openrz 第二轮评审 #171）。两层都过则 merged ≤ 64KB 才落库。
    if req.base_info is not None:
        _validate_base_info_size({**state.session.base_info, **req.base_info})
    # manager.update 抛 I18nError 子类（SessionIllegalTransitionError / Edit / 总字节超限），
    # 全局 I18nError handler 会以 409 / 422 + 本地化 detail 返回，无需在此 catch。
    await manager.update(session_id, req.base_info, req.goal)
    return await _summary_from_session_id(session_id)


# 后台拆除任务的强引用：create_task 只留弱引用，事件循环也只持待执行任务的
# 引用——任务一旦 await 挂起（终算 LLM 可达 135s），没有任何一方持有它，
# GC 随时可能把连 await 中的协程一起收走。这里持有到任务结束为止。
_teardown_tasks: set[_asyncio.Task] = set()


def _teardown_runtime(session_id: str) -> None:
    """后台拆除 runtime（若有）：coaching 终算是一次 LLM 调用（超时上限 135s，= coach.llm_timeout_s × 3），
    不能挂在 HTTP 请求上。拆除完成前 runtime 仍留在 registry，进程关停的
    shutdown drain 能找到并等它跑完。
    """
    rt = registry.get(session_id)
    if rt is None:
        return

    async def _run() -> None:
        try:
            await rt.end()
        except Exception:  # noqa: BLE001
            logger.exception("结束后拆除 runtime 失败：session=%s", session_id)
        finally:
            registry.drop(session_id)

    task = _asyncio.create_task(_run())
    _teardown_tasks.add(task)
    task.add_done_callback(_teardown_tasks.discard)


@router.post("/{session_id}/first-batch")
async def first_batch_interview(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """生成/返回首批评量（幂等）。

    有 runtime（在线或寄存）→ 经 runtime 引擎生成：同一 state 对象 + 引擎锁，
    在线时结果顺带经 WS 推送。无 runtime → 在 DB 状态上生成（in-flight 锁）。
    已结束 / 已生成 / 对话已开始 → 直接返回当前清单，不调 LLM。
    """
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    if state.session.status in TERMINAL_SESSION_STATUSES:
        return _first_batch_response(state)
    # round3 P1.1：first_batch_generated / transcript 非空也走早返回——
    # 这两个分支 engine.first_generate / generate_first_batch 内部都短路不
    # 调 LLM（见 services/coaching/engine.py:152/158 的双重检查），但路由层
    # 不判断就 try_acquire，首评成功后偶发重发 / 重连回查全吃令牌，三路由
    # 共用桶 20 次后用户锁死。
    if state.session.first_batch_generated:
        return _first_batch_response(state)
    if state.transcript:
        return _first_batch_response(state)
    # 限流挪到所有早返回后、调 LLM 前：未调 LLM 的请求不该吃令牌。
    if not _llm_user_limiter.try_acquire(user.user_id):
        raise I18nError(Keys.HTTP_AUTH_RATE_LIMITED, http_status=429)
    rt = registry.get(session_id)
    if rt is not None:
        await rt.engine.first_generate()
        return _first_batch_response(rt.state)
    state = await generate_first_batch(session_id) or state
    return _first_batch_response(state)


def _first_batch_response(state) -> dict:
    return {
        "generated": state.session.first_batch_generated,
        "items": [it.model_dump(mode="json") for it in state.items],
    }


@router.post("/{session_id}/end")
async def end_interview(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """结束访谈（未建立 WS 连接也可结束，如暂停态直接点「结束访谈」）。

    与 WS end 语义一致：manager.end 先把 status 落盘成 ended（请求返回后列表
    即时可见），runtime 收尾放后台任务。若另一客户端仍连着该会话，其连接会在
    runtime 拆除后失效。
    """
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    # manager.end 抛 I18nError 子类，全局 handler 处理。
    await manager.end(session_id)
    _teardown_runtime(session_id)
    return await _summary_from_session_id(session_id)


@router.post("/{session_id}/suspend")
async def suspend_interview(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """暂停访谈（用户点「暂停」按钮时调用）。

    与 end 的区别：不做辅导终局重算，不拆 runtime；只把 status 落盘成 suspended，
    让列表页立即可见暂停状态。WS listen:stop 和 runtime 管线停麦由前端在调用本 API
    之后自行处理（与 end 按钮 same pattern）。
    """
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    await manager.suspend(session_id)
    return await _summary_from_session_id(session_id)


@router.post("/{session_id}/resume")
async def resume_interview(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """继续访谈（用户点「继续」按钮时调用）。

    将 suspended 状态的访谈转回 in_progress。并发限制由 manager.resume() 校验。
    """
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    await manager.resume(session_id)
    return await _summary_from_session_id(session_id)


@router.delete("/{session_id}")
async def delete_interview(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    # manager.delete 抛 I18nError 子类，全局 handler 处理。
    await manager.delete(session_id)
    return {"ok": True}


@router.post("/{session_id}/items/{item_id}/ignore")
async def ignore_item(
    session_id: str,
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    await manager.set_item_status(
        session_id, item_id, "ignore",
        valid_ids=_valid_item_ids(state),
    )
    return {"ok": True}


@router.post("/{session_id}/items/{item_id}/unignore")
async def unignore_item(
    session_id: str,
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    # unignore 是 idempotent 的 discard，无需 valid_ids 校验
    await manager.set_item_status(session_id, item_id, "unignore")
    return {"ok": True}


@router.post("/{session_id}/items/{item_id}/skip")
async def skip_item(
    session_id: str,
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    await manager.set_item_status(
        session_id, item_id, "skip",
        valid_ids=_valid_item_ids(state),
    )
    return {"ok": True}


@router.post("/{session_id}/items/{item_id}/unskip")
async def unskip_item(
    session_id: str,
    item_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    # unskip 是 idempotent 的 discard，无需 valid_ids 校验
    await manager.set_item_status(session_id, item_id, "unskip")
    return {"ok": True}


def _valid_item_ids(state: SessionState) -> Optional[set[str]]:
    """当前访谈模板的合法 item_id 集合（coaching.must_ask[].id）。

    仅看模板快照（创建访谈时的快照），不走 resolve_template 的回退：访谈
    创建后模板被改 / 删项不影响访谈自身的合法集合（既保 immutability，也避免
    admin 删 must_ask 时把活跃访谈标成「错 id」、加项让旧访谈历史里根本没
    有的 id 被误接受）。快照空 / 损坏 / must_ask 为空时返 None，让 manager
    跳过校验——与历史行为一致，旧访谈仍可用。
    """
    snap = state.session.template_snapshot
    if not snap:
        return None
    try:
        tpl = Template(**snap)
    except Exception:  # noqa: BLE001
        return None
    if not tpl.coaching.must_ask:
        return None
    return {m.id for m in tpl.coaching.must_ask}


@router.post("/extract", response_model=ExtractResponse)
async def extract_fields(
    req: ExtractRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """接收转写文本 + 目标字段列表 → LLM 提取 → 返回字段值字典。

    错误响应全部由 LLMError（= I18nError，自带 http_status）透传到全局 handler，
    与 OCR 路径对齐：
    - transcript > 200k 字符 → 422（schema `max_length`，issue #207）
    - LLM context overflow（输入超出模型上限）→ 422（LLMContextOverflowError），
      让前端区分「请缩短 transcript」与「重试」
    - 其他 LLM 错误（鉴权失败 / 服务挂 / JSON 解析失败）→ 502，避免把配置
      问题误导成「文本里没信息」（issue #197）
    """
    from app.adapters.llm.factory import get_llm

    if not req.transcript.strip():
        return ExtractResponse(values={k: "" for k in req.fields})

    # 限流挪到空文本早返回后：表单自动保存循环、前端空串探测都不该吃令牌。
    if not _llm_user_limiter.try_acquire(user.user_id):
        raise I18nError(Keys.HTTP_AUTH_RATE_LIMITED, http_status=429)

    # 构建字段说明（包含类型和格式）
    field_lines = []
    for k in req.fields:
        label = req.field_labels.get(k, k)
        ftype = req.field_types.get(k, 'text')
        hint = ""
        if ftype == 'datetime':
            hint = '（格式：YYYY-MM-DDTHH:MM，如 2026-08-25T15:00）'
        elif ftype == 'duration':
            hint = '（只填数字分钟，如 45）'
        field_lines.append(f"- {k}：{label}{hint}")

    from datetime import date
    today = date.today().isoformat()  # e.g. "2026-08-19"

    # 格式化已填内容供提示词用
    if req.current_values:
        current_lines = [f"- {k}：{v}" for k, v in req.current_values.items() if v]
        current_values_str = "\n".join(current_lines) if current_lines else "（全部为空）"
    else:
        current_values_str = "（全部为空）"

    llm = get_llm()
    output_language = (await get_config_store().get("llm.output_language")) or "zh_cn"
    system_prompt = build_extract_system(
        output_language,
        today=today,
        current_values=current_values_str,
        transcript=req.transcript,
        fields=req.fields,
    )
    user_prompt = (
        f"【待提取字段（仅限以下 key，禁止创建新字段）】\n" + "\n".join(field_lines) + "\n\n"
        "请返回所有字段的完整 JSON 对象（包含已填内容+本次补充）："
    )
    result = await llm.chat_json(system_prompt, user_prompt)
    logger.debug(f"[extract] LLM 原始返回 keys={list(result.keys()) if isinstance(result, dict) else type(result).__name__}")
    # 合并：current_values 兜底，LLM 结果优先级
    values = {}
    for k in req.fields:
        llm_val = result.get(k)
        if llm_val not in (None, ""):
            values[k] = str(llm_val)
        else:
            values[k] = req.current_values.get(k, "")
    logger.debug(f"[extract] 合并后 values keys={list(values.keys())}")

    return ExtractResponse(values=values)


@router.post("/ocr", response_model=OCRResponse)
async def recognize_image(
    req: OCRRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """接收 base64 编码的图片，用后端视觉模型提取文字。

    错误响应统一走 I18nError：
    - base64 解码失败   → 422 + code=http.ocr.image_base64_invalid
    - 图片 > 10MB        → 413 + code=http.ocr.image_too_large
    - 图片格式不在白名单 → 422 + code=http.ocr.image_format_unsupported
    - OCR 未配置          → 502（adapter 抛 Keys.OCR_NOT_CONFIGURED）
    - OCR 调用失败        → 502（adapter 抛 Keys.OCR_INVOKE_FAILED）
    """
    from app.adapters.ocr.factory import get_general_ocr
    from app.core.i18n.errors import I18nError

    import base64 as _b64

    try:
        image_bytes = _b64.b64decode(req.image_base64)
    except Exception:
        raise I18nError(Keys.HTTP_OCR_IMAGE_BASE64_INVALID, http_status=422)

    if len(image_bytes) > 10 * 1024 * 1024:
        raise I18nError(
            Keys.HTTP_OCR_IMAGE_TOO_LARGE, http_status=413,
            size_mb=len(image_bytes) / (1024 * 1024),
        )

    if not _is_supported_image_format(image_bytes):
        raise I18nError(
            Keys.HTTP_OCR_IMAGE_FORMAT_UNSUPPORTED, http_status=422,
        )

    # 限流挪到格式/大小早返回后：坏图、超限图、非支持格式都不该吃令牌——
    # 前端 OCR 按钮偶发重复触发、或图传一半失败重传，都不该锁自己。
    if not _llm_user_limiter.try_acquire(user.user_id):
        raise I18nError(Keys.HTTP_AUTH_RATE_LIMITED, http_status=429)

    try:
        ocr = get_general_ocr()
    except ValueError as e:
        # factory 已知错误：ocr.type 未注册等配置问题 → 502 而非 500
        logger.warning("OCR factory 构造失败：%s", e)
        raise I18nError(Keys.OCR_NOT_CONFIGURED, http_status=502)
    if not ocr.configured:
        # 不在路由层拼字符串 — 直接让 adapter 自己抛 Keys.OCR_NOT_CONFIGURED。
        # 但 factory.get_general_ocr() 已经返回 provider 实例了，recognize() 内部会判
        # configured；这里只防御性短路（factory 不会返未配置的实例，但语义更清晰）。
        raise I18nError(Keys.OCR_NOT_CONFIGURED, http_status=502)

    # 不再 try/except Exception 转换 — adapter 层已经抛 I18nError(Keys.OCR_*, 502)，
    # 由 app.py 的全局 handler 转 {detail, code} 响应。其他真异常（KeyError、
    # ValueError 等 programming error）走 FastAPI 兜底 500，由告警系统捕获。
    text = await ocr.recognize(image_bytes, prompt=OCR_PROMPT)
    return OCRResponse(text=text or "")


# ---- 笔记（键盘 / 手写） ----

# 笔记与画板 POST 允许的状态:必须已 "开始访谈"(in_progress)。
# suspended / created / setting_up / ended / done / extracting 均拒 409。
_NOTE_ALLOWED_STATUSES = {SessionStatus.IN_PROGRESS}


async def _load_session_for_note(session_id: str, user_id: str) -> SessionState:
    """笔记与画板 handler 共用:鉴权 + 状态机校验(仅 in_progress)。

    DELETE 状态不限(handler 用 manager.get 不走此校验),允许 ended 清理。
    """
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user_id:
        # 资源隔离：不是本人的访谈一律 404（不泄露存在性）
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    if state.session.status not in _NOTE_ALLOWED_STATUSES:
        raise I18nError(
            Keys.WS_SESSION_ENDED, http_status=409,
        )
    return state


def _remove_image_ids(state: SessionState, ids: list[int]) -> bool:
    """mutate_state_auto 用的 mutator:从 state.handwriting_notes 按 image_id 集合删段。

    返回 True 表示真删了(触发落盘),False 表示 ids 都没命中(不落盘)。
    """
    ids_set = set(ids)
    before = len(state.handwriting_notes)
    state.handwriting_notes = [
        n for n in state.handwriting_notes if n.image_id not in ids_set
    ]
    return len(state.handwriting_notes) < before


@router.post("/{session_id}/notes/keyboard", response_model=KeyboardNoteResponse)
async def upsert_keyboard_note(
    session_id: str,
    req: CreateKeyboardNoteRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """UPSERT 键盘笔记:每 session+user 唯一 1 行,覆盖语义。

    不做去重 —— 用户「调整提交」是「我现在要传达给 LLM 的最终答案」,旧版本作废。
    """
    from app.services.keyboard.service import upsert_keyboard_text_auto

    state = await _load_session_for_note(session_id, user.user_id)
    await upsert_keyboard_text_auto(
        session_id=state.session.id,
        user_id=user.user_id,
        text=req.text,
        client_created_at=req.client_created_at,
    )
    # 读最新行返回(updated_at 由 onupdate 触发)
    from app.services.keyboard.service import get_keyboard_text_auto

    note = await get_keyboard_text_auto(
        session_id=state.session.id, user_id=user.user_id,
    )
    # 注入 state:调度防抖重算(arm pause_s 后才 fire,与 ASR 句段走同一 _arm 路径)
    from app.services.sessions.runtime import registry as runtime_registry

    runtime = runtime_registry.get(state.session.id)
    if runtime is not None:
        await runtime.inject_keyboard_text(req.text)
    return KeyboardNoteResponse(
        session_id=note.session_id,
        user_id=note.user_id,
        text=note.text,
        client_created_at=note.client_created_at,
        updated_at=note.updated_at,
    )


@router.get("/{session_id}/notes/keyboard", response_model=KeyboardListResponse)
async def get_keyboard_note(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """拉该 session 当前键盘文本(最多 1 行)。"""
    state = await _load_session_for_note(session_id, user.user_id)
    from app.services.keyboard.service import get_keyboard_text_auto

    note = await get_keyboard_text_auto(
        session_id=state.session.id, user_id=user.user_id,
    )
    if note is None:
        return KeyboardListResponse(item=None)
    return KeyboardListResponse(item=KeyboardNoteResponse(
        session_id=note.session_id,
        user_id=note.user_id,
        text=note.text,
        client_created_at=note.client_created_at,
        updated_at=note.updated_at,
    ))


# ---- 画板 state ----

@router.post(
    "/{session_id}/canvases/{canvas_index}",
    response_model=SaveCanvasResponse,
)
async def save_canvas(
    session_id: str,
    req: SaveCanvasRequest,
    canvas_index: int = Path(..., ge=1, description="前端自增画板号,1/2/3..."),
    user: CurrentUser = Depends(get_current_user),
):
    """upsert 画板 state + 截图(payload + filedata 一次 POST 都必填)。

    payload 走 canvas hash 跳过,filedata 走 image hash 跳过——同画板多次
    POST 仅当两边内容都一致时才都 skip。canvas_index 与 image_id 不一定
    相等:create_pending_image_auto 内部 backfill canvas_index 到行。
    """
    state = await _load_session_for_note(session_id, user.user_id)

    # ---- 校验阶段:任何 DB 写入前的硬校验(避免脏写)----
    import base64 as _b64
    from app.services.handwriting.service import (
        compute_image_hash_from_bytes,
        sniff_image_format,
    )

    try:
        image_bytes = _b64.b64decode(req.filedata)
    except Exception:
        raise I18nError(Keys.HTTP_OCR_IMAGE_BASE64_INVALID, http_status=422)
    if len(image_bytes) > 10 * 1024 * 1024:
        raise I18nError(
            Keys.HTTP_OCR_IMAGE_TOO_LARGE, http_status=413,
            size_mb=len(image_bytes) / (1024 * 1024),
        )
    image_format = sniff_image_format(image_bytes)
    if not image_format:
        raise I18nError(
            Keys.HTTP_OCR_IMAGE_FORMAT_UNSUPPORTED, http_status=422,
        )

    # 手写 OCR 未配置 → 502 + 不落库 / 不 fire task(handler 同步拦截)
    from app.core.config_store import get_config_store

    cfg = get_config_store()
    hw_type = cfg.get_sync("handwriting.type", "baidu") or "baidu"
    # 必填 key 按 type 区分:openai 模式不需要 secret_key(Baidu 专属)
    required_keys = ("handwriting.base_url", "handwriting.api_key", "handwriting.model")
    if hw_type == "baidu":
        required_keys = ("handwriting.base_url", "handwriting.api_key",
                         "handwriting.secret_key", "handwriting.model")
    missing = [k for k in required_keys if not (cfg.get_sync(k) or "")]
    if missing:
        raise I18nError(
            Keys.HANDWRITING_NOT_CONFIGURED, http_status=502,
        )

    image_hash = compute_image_hash_from_bytes(image_bytes)

    # ---- DB 写入阶段(校验通过后)----
    from app.services.handwriting.canvas_service import upsert_canvas_payload_auto
    from app.services.handwriting.service import (
        create_pending_image_auto,
        replace_canvas_image_auto,
    )

    # canvas 行存在 → UPDATE(image 字段覆盖),否则 INSERT
    replace_result = await replace_canvas_image_auto(
        session_id=state.session.id,
        user_id=user.user_id,
        image_base64=req.filedata,
        image_hash=image_hash,
        image_format=image_format,
        image_bytes_size=len(image_bytes),
        canvas_index=canvas_index,
        client_created_at=req.client_updated_at,
    )
    if replace_result is not None:
        row, ocr_task_fired = replace_result
    else:
        # canvas 行不存在(首次 POST)→ INSERT + backfill canvas_index
        row, created = await create_pending_image_auto(
            session_id=state.session.id,
            user_id=user.user_id,
            image_base64=req.filedata,
            image_hash=image_hash,
            image_format=image_format,
            image_bytes_size=len(image_bytes),
            client_created_at=req.client_updated_at,
            canvas_index=canvas_index,
        )
        # 新建行 → 触发 OCR;dedup 命中已存在行 → 跳过(已 ocr 过)。
        # 注意:dedup 命中 ocr_status=failed 的旧行也跳过——边缘 case,
        # 留给用户在画板上手动重传(下次 POST canvas_index 走 replace 路径
        # 按 image_hash 变化重置 OCR 状态机)。
        ocr_task_fired = created

    # payload upsert(无论 canvas 行新建还是已存在,都走 hash 跳过 / 覆盖)
    payload_result = await upsert_canvas_payload_auto(
        session_id=state.session.id,
        user_id=user.user_id,
        canvas_index=canvas_index,
        payload=req.payload,
    )

    image_id = row.id

    if ocr_task_fired:
        # 重画清旧 OCR:否则新 task 完成时 dedup 命中早退,state 卡老图
        from app.services.sessions.runtime import registry as runtime_registry

        runtime = runtime_registry.get(state.session.id)
        if runtime is not None:
            await runtime.remove_handwriting_notes([row.id])

        from app.services.handwriting.ocr_task import _ocr_with_retry

        task = _asyncio.create_task(_ocr_with_retry(row.id, state.session.id))
        _ocr_bg_tasks.add(task)
        task.add_done_callback(_ocr_bg_tasks.discard)

    return SaveCanvasResponse(
        canvas_index=canvas_index,
        payload_skipped=payload_result.payload_skipped if payload_result else False,
        payload_updated=payload_result.payload_updated if payload_result else False,
        image_id=image_id,
        ocr_task_fired=ocr_task_fired,
    )


@router.get(
    "/{session_id}/canvases",
    response_model=CanvasListResponse,
)
async def list_canvases(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """返该 session 该 user 全部画板——canvas_index 升序(NULL 行在后)。

    不校验 session 状态(报告页要展示 ended/done 状态下的历史画板)。
    """
    from app.services.handwriting.canvas_service import list_canvases_auto

    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    rows = await list_canvases_auto(
        session_id=state.session.id,
        user_id=user.user_id,
    )
    return CanvasListResponse(items=[
        {
            "canvas_index": r.canvas_index,  # 不替换 NULL:纯 OCR 图行无 canvas 概念
            "image_id": r.id,
            "image_base64": r.image_base64,
            "image_format": r.image_format,
            "ocr_status": r.ocr_status,
            "text": r.text,
            "canvas_payload": r.canvas_payload,  # nullable:某些行只有图无 state
            "client_updated_at": r.client_created_at,
            "created_at": r.created_at,
        }
        for r in rows
    ])


@router.delete(
    "/{session_id}/canvases/{canvas_index}",
    response_model=DeleteCanvasResponse,
)
async def delete_canvas(
    session_id: str,
    canvas_index: int = Path(..., ge=1, description="前端自增画板号,1/2/3..."),
    user: CurrentUser = Depends(get_current_user),
):
    """删除画板(连带图行)。

    幂等:不存在返 deleted_ids=[]。删除后清理 state.handwriting_notes
    对应 OCR 文本(如有),并 arm 防抖重算。
    """
    from app.services.handwriting.canvas_service import delete_canvas_auto

    # DELETE canvas 不强制状态机:ended 状态用户也能清理误操作的画板。
    # POST 才强制 _NOTE_ALLOWED_STATUSES(不允许 ended 后还在写)。
    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    image_id = await delete_canvas_auto(
        session_id=state.session.id,
        user_id=user.user_id,
        canvas_index=canvas_index,
    )
    if image_id is not None:
        # 同步清理 state.handwriting_notes 里该 image_id 段——LLM 不再看到已删的 OCR 文本
        from app.services.sessions.runtime import registry as runtime_registry

        runtime = runtime_registry.get(state.session.id)
        if runtime is not None:
            await runtime.remove_handwriting_notes([image_id])
        else:
            # runtime 已 evict/drop(suspended/ended session 从新标签接入)→
            # 镜像列直接读 → 过滤 → 写回。走 mutate_state_auto 持锁 RMW,
            # 避免并发删/OCR 注入撞车丢段。
            from app.persistence.repositories.interview import interview_repo

            await interview_repo.mutate_state_auto(
                state.session.id,
                lambda s: _remove_image_ids(s, [image_id]),
                fields={"notes"},
            )
        return DeleteCanvasResponse(deleted_ids=[image_id])
    return DeleteCanvasResponse(deleted_ids=[])


@router.post(
    "/{session_id}/canvases/batch-delete",
    response_model=DeleteCanvasResponse,
)
async def batch_delete_canvases(
    session_id: str,
    req: DeleteCanvasRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """批量删除画板,body 指定 canvas_indexes 列表。

    跨 session/跨 user 的 canvas_index 静默跳过(handler 三匹配)。
    删除后同步清理 state.handwriting_notes 里各 image_id 段。
    """
    from app.services.handwriting.canvas_service import delete_canvases_batch_auto
    from app.services.sessions.runtime import registry as runtime_registry

    state = await manager.get(session_id)
    if state is None or state.session.user_id != user.user_id:
        raise I18nError(Keys.HTTP_SESSION_NOT_FOUND, http_status=404)
    deleted_ids = await delete_canvases_batch_auto(
        session_id=state.session.id,
        user_id=user.user_id,
        canvas_indexes=req.canvas_indexes,
    )
    if deleted_ids:
        runtime = runtime_registry.get(state.session.id)
        if runtime is not None:
            await runtime.remove_handwriting_notes(deleted_ids)
        else:
            # runtime 已 evict/drop → 镜像列清理(单删路径已有同款逻辑)
            from app.persistence.repositories.interview import interview_repo

            await interview_repo.mutate_state_auto(
                state.session.id,
                lambda s: _remove_image_ids(s, deleted_ids),
                fields={"notes"},
            )
    return DeleteCanvasResponse(deleted_ids=deleted_ids)

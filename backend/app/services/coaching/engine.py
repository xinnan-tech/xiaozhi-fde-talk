"""辅导引擎：全量重算 → 推 coaching.update。

【__init__ 是 sync】B 类配置走 ConfigStore._cache（同步预热），__init__ 设 DEFAULTS 默认值；
构造后由 SessionRuntime 调 `engine.ainit()` 覆盖为 DB 当前值（生产必走）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Awaitable, Callable, Optional

from app.adapters.llm.base import LLMError, LLMProvider
from app.adapters.llm.factory import get_llm
from app.core.i18n.messages import Keys
from app.core.i18n.pivot import with_lang_fallback
from app.core.outbound_send import safe_send
from app.domain.coaching import CoachingItem, ItemStatus
from app.domain.session import SessionStatus
from app.persistence.repositories.interview import interview_repo
from app.services.coaching.contract import validate_llm_output
from app.services.coaching.facts import FactDatabase
from app.services.coaching.prompt import build_first_batch, build_system, build_user
from app.services.sessions.state import SessionState
from app.services.template.loader import resolve_template

logger = logging.getLogger(__name__)

SendFn = Callable[[dict], Awaitable[None]]

# 会话终态集合（ended/extracting/done）：终态会话不再生成首评（路由层已挡，
# 引擎兜底拆除窗口期等非路由调用）。路由与引擎共用。
TERMINAL_SESSION_STATUSES = {SessionStatus.ENDED, SessionStatus.EXTRACTING, SessionStatus.DONE}


def _coaching_update(phase: str, version: int, items: list[CoachingItem]) -> dict:
    return {
        "type": "coaching.update",
        "phase": phase,
        "version": version,
        "items": [it.model_dump(mode="json") for it in items],
        "skipped_ack": [],
    }


class CoachingEngine:
    """辅导引擎。

    触发参数从 ConfigStore 注入：
      - pause_s              : 停顿防抖窗口（新句后静默此时长 → 一段话说完）
      - max_pending_segments : 未消费段数阈值（连续说话兜底触发）
      - min_interval_s       : 两次重算最小间隔（限频，兼失败退避）
      - llm_timeout_s        : LLM 硬超时

    会话期固定（创建时一次性读，新会话才生效）。
    """

    def __init__(self, state: SessionState, send: SendFn) -> None:
        # 同步部分：仅设基础字段 + ConfigStore DEFAULTS 默认值（让 unit 测试无需 ainit() 也能用）。
        # 生产环境 SessionRuntime.ainit() 会覆盖这些值为 DB 当前值。
        self.state = state
        self._ws_send = send
        # template 可能为 None（缓存 miss + snapshot 损坏/缺失）；调用方（runtime
        # / bind 路径）应保证 template_id 在缓存或 snapshot 至少其一存在，否则
        # 后续 LLM 调用 build_first_batch(None)/build_system(None) 会 AttributeError
        # ——属于配置错误，让其显式失败比静默降级更易定位。
        self.template = resolve_template(
            state.session.template_id, state.session.template_snapshot,
        )
        self._llm: Optional[LLMProvider] = None  # ainit() 后注入；None 表示未初始化
        self._pause_s: float = 5.0                 # DEFAULTS: coach.pause_s
        self._max_pending_segments: int = 8        # DEFAULTS: coach.max_pending_segments
        self._min_interval_s: float = 10.0         # DEFAULTS: coach.min_interval_s
        self._llm_timeout_s: float = 45.0          # DEFAULTS: coach.llm_timeout_s
        self.version = 0
        self._in_progress = False
        self._pending_segments = 0     # 自上次触发以来未消费的新段数
        self._timer_paused = False    # listen:stop 暂停调度
        self._closed = False          # end 到达后不再通过 WS 发消息
        self._last_ts = 0.0           # 上次触发时刻（min_interval 限频基准）
        self._transcript_len_at_last = 0  # 据此判断窗口非空（成功才推进）
        self._facts = FactDatabase()
        self._sched_task: asyncio.Task | None = None
        self._tpl_meta = {
            m.id: (m.priority if m.priority is not None else 99, m.desc)
            for m in (self.template.coaching.must_ask if self.template else [])
        }
        self._bg: set[asyncio.Task] = set()
        self._recompute_lock = asyncio.Lock()
        self._bound: bool = True
        self._initialized = False
        # 非 LLM 路径可能引用；每次 LLM 调用前都会再读 ConfigStore 覆盖（见 _read_output_language）。
        self._output_language: str = "zh_cn"
        self._persist: Callable[[], Awaitable[None]] = lambda: interview_repo.save_state_auto(self.state)

    def ainit(self) -> None:
        """同步初始化：ConfigStore._cache + LLM 单例。SessionRuntime 构造后必须调一次。

        名字仍为 ainit() 以保留 runtime.py/handler.py 的调用契约；
        由于 B 类配置已走同步 _cache，方法本身无需 await。
        """
        if self._initialized:
            return
        from app.core.config_store import DEFAULTS, get_config_store
        store = get_config_store()
        def _g(key: str, cast=float, default="0"):
            raw = store.get_sync(key, DEFAULTS.get(key, default))
            return cast(raw)
        self._pause_s = _g("coach.pause_s", float, "5.0")
        self._max_pending_segments = _g("coach.max_pending_segments", int, "8")
        self._min_interval_s = _g("coach.min_interval_s", float, "10.0")
        self._llm_timeout_s = _g("coach.llm_timeout_s", float, "45.0")
        self._llm = get_llm()
        self._initialized = True

    def _read_output_language(self) -> str:
        """每次 prompt 构建前现读 llm.output_language，不缓存。

        ainit 时读一次作为兜底（_output_language 字段保留供非 LLM 路径用），
        但每次 _recompute / first_generate / _final_recompute 调 LLM 前必须现读——
        否则管理员改语种后，旧 session 一直用旧值直到结束。
        """
        from app.core.config_store import get_config_store
        raw = get_config_store().get_sync("llm.output_language")
        return (raw or "zh_cn").strip().lower() or "zh_cn"

    # ── 外部钩子（由 WSHandler 调用）─────────────────────────────────

    async def first_compute(self) -> None:
        """首算：直接把当前清单（模板 must_ask）推给客户端。"""
        self.version += 1
        await self._safe_send(_coaching_update("final", self.version, self.state.items))
        logger.info("coaching 首算 v%s：%d 条", self.version, len(self.state.items))
        self._transcript_len_at_last = len(self.state.transcript)
        self._kick_first_generate_if_pending()

    async def first_generate(self) -> None:
        """首评生成：结合访谈对象/背景/目标用 LLM 定制第一批问题（每会话一次）。

        与事件重算同一把锁串行；拿锁后复查——对话已开始则放弃（清单归事件重算）。
        失败保留模板种子且不置 flag，下次绑定/预热自然重试。
        """
        if (self.state.session.first_batch_generated or self._closed
                or self.state.session.status in TERMINAL_SESSION_STATUSES):
            return
        if self._llm is None:
            raise RuntimeError("coaching engine not initialized (ainit not called)")
        async with self._recompute_lock:
            if (self.state.session.first_batch_generated or self.state.transcript
                    or self._closed
                    or self.state.session.status in TERMINAL_SESSION_STATUSES):
                return
            self._in_progress = True
            self.version += 1
            version = self.version
            await self._safe_send(_coaching_update("recomputing", version, []))
            try:
                system, user = build_first_batch(self.template, self.state.session, self._read_output_language())
                parsed = await self._llm_pivot_then_parse_json(
                    system,
                    lambda l: build_first_batch(self.template, self.state.session, l)[0],
                    user,
                    self._read_output_language(),
                )
                items = self._apply(validate_llm_output(parsed))
                for i, it in enumerate(items):
                    it.priority = i + 1  # 输出顺序即建议发问顺序
                self.state.items = items
                self.state.session.first_batch_generated = True
                await self._persist()
                await self._safe_send(_coaching_update("final", version, self.state.items))
                logger.info("coaching 首评生成 v%s 完成：%d 条", version, len(items))
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                logger.warning("coaching 首评生成 v%s LLM 超时，保留模板种子", version)
                await self._safe_send(_coaching_update("final", version, self.state.items))
            except LLMError as e:
                logger.warning("coaching 首评生成 v%s 失败，保留模板种子：%s", version, e)
                await self._safe_send(_coaching_update("final", version, self.state.items))
            except Exception as e:  # noqa: BLE001
                logger.exception("coaching 首评生成 v%s 异常：%s", version, e)
                await self._safe_send(_coaching_update("final", version, self.state.items))
            finally:
                self._in_progress = False
                self._last_ts = time.time()

    def _kick_first_generate_if_pending(self) -> None:
        """绑定路径（首算 / 重连 snapshot）末尾统一检查：首评未生成且访谈未开聊
        （未经 HTTP 预热的直连，或寄存期间 PATCH 实际变更清了 flag）→ 后台补一次
        首评。_llm 未初始化（未 ainit）时不补——生产路径 runtime.ainit 必先于 bind。
        """
        if (self._llm is not None
                and not self.state.session.first_batch_generated
                and not self.state.transcript):
            self._track(self.first_generate())

    async def resend_current(self) -> None:
        """重连后重推当前清单（snapshot）。

        不递增 version、不触发重算——仅把最新清单再推一次，
        让重连客户端立即看到当前辅导状态。
        """
        await self._safe_send(_coaching_update("final", self.version, self.state.items))
        self._kick_first_generate_if_pending()

    async def on_end(self) -> None:
        self._closed = True
        if self._sched_task:
            self._sched_task.cancel()
            self._sched_task = None
        try:
            await asyncio.wait_for(self._final_recompute(), timeout=self._llm_timeout_s * 3)
        except asyncio.TimeoutError:
            logger.warning("coaching on_end final 超时 %ss，best-effort 落盘", int(self._llm_timeout_s * 3))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("coaching on_end final 异常: %s", e)
        await self._drain_bg()

    def on_listen_pause(self) -> None:
        self._timer_paused = True
        if self._sched_task:
            self._sched_task.cancel()
            self._sched_task = None

    def on_listen_resume(self) -> None:
        self._timer_paused = False

    def on_unbind(self) -> None:
        """协议层断开：暂停调度，保留全部状态（不 drain / 不 close）。"""
        self._bound = False
        self.on_listen_pause()

    def on_bind(self) -> None:
        self._bound = True

    def _track(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return task

    async def _drain_bg(self) -> None:
        for t in list(self._bg):
            t.cancel()
        if self._bg:
            await asyncio.gather(*self._bg, return_exceptions=True)
        self._bg.clear()
        if self._sched_task:
            self._sched_task.cancel()
            await asyncio.gather(self._sched_task, return_exceptions=True)
            self._sched_task = None

    # ── 内部重算逻辑 ─────────────────────────────────────────────────

    async def _safe_send(self, msg: dict) -> None:
        await safe_send(self._ws_send, msg)

    def on_utterance(self) -> None:
        """新转写段定稿（runtime 建段后调用）：累计窗口并（重新）武装调度。

        停顿防抖语义：每句到达都从头计时，静默满 pause_s 即"一段话说完"；
        连续说话防抖一直被重置 → 由段数阈值兜底触发。
        """
        self._pending_segments += 1
        if self._pending_segments >= self._max_pending_segments:
            self._arm(0.0, "段数阈值")
        else:
            self._arm(self._pause_s, "停顿防抖")

    def on_listen_stopped(self) -> None:
        """listen:stop 落定（管线 flush 完、尾句已入 transcript）后由 runtime 调用。

        尾句窗口非空则补一次重算，让清单带着最新内容进入暂停态。
        在途重算期间跳过（窗口保留，由 resume 后的新事件或结束 final 消费）。
        """
        if self._closed or not self._bound or self._in_progress:
            return
        if len(self.state.transcript) <= self._transcript_len_at_last:
            return
        self._pending_segments = 0
        self._track(self._recompute())

    def _arm(self, delay_s: float, reason: str) -> None:
        """单槽调度：新事件取消旧任务从头计时。"""
        if self._timer_paused or self._closed or not self._bound:
            return
        if self._sched_task is not None:
            self._sched_task.cancel()
        self._sched_task = asyncio.create_task(self._sched_after(delay_s, reason))

    async def _sched_after(self, delay_s: float, reason: str) -> None:
        await asyncio.sleep(delay_s)
        remaining = self._min_interval_s - (time.time() - self._last_ts)
        if remaining > 0:
            await asyncio.sleep(remaining)  # 限频：推迟而非丢弃
        await self._sched_fire(reason)

    async def _sched_fire(self, reason: str) -> None:
        if self._timer_paused or self._closed or not self._bound or self._in_progress:
            return
        if len(self.state.transcript) <= self._transcript_len_at_last:
            self._pending_segments = 0
            return
        new_segs = len(self.state.transcript) - self._transcript_len_at_last
        logger.info("coaching 事件重算（%s，%d 条新段）", reason, new_segs)
        self._pending_segments = 0
        self._track(self._recompute())

    async def _recompute(self) -> None:
        if self._llm is None:
            raise RuntimeError("coaching engine not initialized (ainit not called)")
        async with self._recompute_lock:
            self._in_progress = True
            self.version += 1
            version = self.version
            await self._safe_send(_coaching_update("recomputing", version, []))
            try:
                system = build_system(self.template, self.state.session.goal, self._read_output_language())
                user = build_user(self.state)
                parsed = await self._llm_pivot_then_parse_json(
                    system,
                    lambda l: build_system(self.template, self.state.session.goal, l),
                    user,
                    self._read_output_language(),
                )
                self.state.items = self._apply(validate_llm_output(parsed))
                self._transcript_len_at_last = len(self.state.transcript)
                await self._persist()
                await self._safe_send(_coaching_update("final", version, self.state.items))
                logger.info("coaching 重算 v%s 完成：%d 条", version, len(self.state.items))
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                logger.warning("coaching 重算 v%s LLM 超时 %ss，保留上一份", version, int(self._llm_timeout_s))
                await self._safe_send(_coaching_update("final", version, self.state.items))
            except LLMError as e:
                logger.warning("coaching 重算 v%s 失败，保留上一份：%s", version, e)
                await self._safe_send(_coaching_update("final", version, self.state.items))
            except Exception as e:  # noqa: BLE001
                logger.exception("coaching 重算 v%s 异常：%s", version, e)
                await self._safe_send(_coaching_update("final", version, self.state.items))
            finally:
                self._in_progress = False
                self._last_ts = time.time()
                if (not self._closed and self._bound and not self._timer_paused
                        and len(self.state.transcript) > self._transcript_len_at_last):
                    # 失败（游标未推进）或期间又有新段 → 满 min_interval 后续算
                    self._arm(0.0, "续算")

    async def _final_recompute(self) -> None:
        if self._llm is None:
            raise RuntimeError("coaching engine not initialized (ainit not called)")
        async with self._recompute_lock:
            self._in_progress = True
            self.version += 1
            version = self.version
            await self._safe_send(_coaching_update("recomputing", version, []))
            try:
                system = build_system(self.template, self.state.session.goal, self._read_output_language())
                user = build_user(self.state)
                parsed = await self._llm_pivot_then_parse_json(
                    system,
                    lambda l: build_system(self.template, self.state.session.goal, l),
                    user,
                    self._read_output_language(),
                )
                self.state.items = self._apply(validate_llm_output(parsed))
                await self._persist()
                await self._safe_send(_coaching_update("final", version, self.state.items))
                logger.info("coaching 最终重算 v%s（end）完成：%d 条", version, len(self.state.items))
            except asyncio.TimeoutError:
                logger.warning("coaching 最终重算 v%s LLM 超时，保留上一份", version)
                await self._safe_send(_coaching_update("final", version, self.state.items))
            except LLMError as e:
                logger.warning("coaching 最终重算 v%s 失败，保留上一份：%s", version, e)
                await self._safe_send(_coaching_update("final", version, self.state.items))
            except Exception as e:  # noqa: BLE001
                logger.exception("coaching 最终重算 v%s 异常：%s", version, e)
                await self._safe_send(_coaching_update("final", version, self.state.items))
            finally:
                self._in_progress = False
                self._last_ts = time.time()

    async def _llm_pivot_then_parse_json(
        self,
        system: str,
        system_factory: Callable[[str], str],
        user: str,
        lang: str,
    ) -> dict:
        """pivot-aware chat_text 调用 → JSON dict。

        system 是主路 system（调用方已构建好——保证 spy 能看到首次构建）。
        system_factory 仅在 pivot 时按 fallback_lang 重建 system。

        走 chat_text(..., json_mode=True)：raw text 用于 detect_script / 解析。
        chat_json 的 fence+parse 逻辑在这里镜像复刻（_extract_json_dict）。
        """
        async def _call(s: str, u: str) -> str:
            return await asyncio.wait_for(
                self._get_llm().chat_text(s, u, json_mode=True),
                timeout=self._llm_timeout_s,
            )
        text, _ = await with_lang_fallback(_call, system, system_factory, user, lang)
        return self._extract_json_dict(text)

    def _extract_json_dict(self, text: str) -> dict:
        """Extract first {...} block and parse — mirrors chat_json fence+parse logic."""
        fence = re.search(r"\{.*\}", text, re.DOTALL)
        if fence is None:
            raise LLMError(
                Keys.LLM_NO_JSON_BLOCK, http_status=502, snippet=text[:200],
            )
        try:
            return json.loads(fence.group(0))
        except json.JSONDecodeError as e:
            raise LLMError(
                Keys.LLM_INVALID_JSON, http_status=502,
                err=str(e), json_str=text[:200],
            ) from e

    def _get_llm(self) -> LLMProvider:
        """现取 LLM 单例：admin 改 base_url 后 factory.invalidate 已 aclose 旧 provider，
        此处拿到新实例，不会持有已关闭的 client。"""
        return get_llm()

    def _apply(self, llm_items: list) -> list[CoachingItem]:
        existing = {it.id for it in self.state.items}
        seen: set[str] = set()
        next_n = 1
        result: list[CoachingItem] = []

        for item in llm_items:
            item_id = item.id
            if item_id is None:
                while f"n{next_n}" in existing or f"n{next_n}" in seen:
                    next_n += 1
                item_id = f"n{next_n}"
                next_n += 1
            if item_id in seen:
                continue
            seen.add(item_id)

            status = item.status if isinstance(item.status, ItemStatus) else ItemStatus.TODO
            priority, desc = self._tpl_meta.get(item_id, (99, ""))
            text = item.text.strip() if item.text else ""
            if not text:
                continue

            # 1) 先算 corrections —— 在 CoachingItem(...) 构造之前
            corrections = getattr(item, "corrected_segments", None) or {}
            corrections = corrections if (corrections and status == ItemStatus.DONE) else {}

            # 2) 写回 transcript 段的 corrected_text。
            # 一个段可能支撑多条 done；后写覆盖前写——LLM 不该对同一段给出冲突纠正。
            if corrections:
                seg_by_id = {s.seg_id: s for s in self.state.transcript}
                for seg_id, corrected in corrections.items():
                    seg = seg_by_id.get(seg_id)
                    if seg is not None and corrected and corrected.strip():
                        seg.corrected_text = corrected.strip()

            # 3) 构造 CoachingItem 时把 corrected_segments 传出去 —— 前端 done 卡片用它显「已纠错 N 处」徽标
            result.append(CoachingItem(
                id=item_id,
                text=text,
                status=status,
                reason=item.reason.strip() if item.reason else "",
                priority=priority,
                desc=desc,
                corrected_segments=corrections,
            ))
            if status == ItemStatus.DONE and item.covered_segments:
                self.state.coverage[item_id] = list(item.covered_segments)

        for it in result:
            if it.id in self.state.ignored_ids:
                it.status = ItemStatus.IGNORED
            elif it.id in self.state.skipped_ids:
                it.status = ItemStatus.SKIPPED
        # LLM 可能把被忽略/跳过的项当成 done 直接丢掉（对话里已覆盖就标 done 不再返），
        # 但用户明确说过「不要问」/「本轮跳过」，应保留操作痕迹——把上一轮的快照补回
        # result 并强制置为 IGNORED/SKIPPED，不让用户动作被静默吞掉。
        if self.state.ignored_ids or self.state.skipped_ids:
            in_result = {it.id for it in result}
            for prev in self.state.items:
                if prev.id in in_result:
                    continue
                if prev.id in self.state.ignored_ids:
                    result.append(prev.model_copy(update={"status": ItemStatus.IGNORED}))
                elif prev.id in self.state.skipped_ids:
                    result.append(prev.model_copy(update={"status": ItemStatus.SKIPPED}))
        return result

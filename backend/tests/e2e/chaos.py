"""E2E 混沌测试客户端：模拟浏览器前端驱动访谈 WS 全流程。

一个 ChaosClient = 一个 WS 连接（身份 + 收发 + 帧记录）；E2EApi 封装 REST 侧
（登录 / 建访谈 / 结束 / 查询）。帧流水落 JSONL 便于事后排查，断言只看内存副本。
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import struct
import time
import uuid

import httpx
import websockets

AUDIO = pathlib.Path(__file__).parent / "audio" / "interview.webm"  # 9m16s 真实访谈录音

AUDIO_PARAMS = {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}
CHUNK_BYTES = 800          # ~200ms 的 32kbps opus
CHUNK_INTERVAL = 0.2       # 与前端麦克风的到包节奏一致
HANDSHAKE_TIMEOUT = 15
TEMPLATE_ID = "pm-research"
# 音频前导静音/低语时长经验值 ≈12s，但用 "首段 asr 到" 取代硬编码 sleep 更稳；
# 这里是硬超时兜底，避免 ASR 挂掉时挂死整个用例。
AUDIO_LEAD_S = 12.0        # 首次出段前最长等待
ASR_DEADLINE_S = 120.0     # 若 N 秒内还没出任何段，认为 ASR 异常挂死

_SEG_RE = re.compile(r"s(\d+)")


def _ws_base(http_base: str) -> str:
    return http_base.replace("https://", "wss://").replace("http://", "ws://")


class ChaosClient:
    def __init__(self, name: str, token: str, sid: str, *, base_url: str,
                 client_id: str | None = None, logdir: pathlib.Path | None = None):
        self.name = name
        self.token = token
        self.sid = sid
        self.client_id = client_id or str(uuid.uuid4())
        self.ws_base = _ws_base(base_url)
        self.logdir = logdir

        self.ws: websockets.ClientConnection | None = None
        self.seq = 0
        self.records: list[dict] = []          # 全部收发 + 事件的内存副本
        self.close_code: int | None = None
        self.close_reason: str | None = None

        self.reader_task: asyncio.Task | None = None
        self.hello_event = asyncio.Event()
        self.conflict_event = asyncio.Event()
        self.kicked_event = asyncio.Event()
        self.ended_event = asyncio.Event()
        self.first_asr_event = asyncio.Event()
        self.closed_event = asyncio.Event()
        self.hello_reply: dict | None = None

        self._f = (logdir / f"{name}.jsonl").open("a", encoding="utf-8") if logdir else None

    # ---- 记录 ----

    def _log(self, dirn: str, kind: str, data) -> None:
        rec = {"t": round(time.time(), 3), "dir": dirn, "kind": kind, "data": data}
        self.records.append(rec)
        if self._f:
            self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._f.flush()

    @property
    def in_frames(self) -> list[dict]:
        return [r for r in self.records if r["dir"] == "in"]

    def frames_of(self, kind: str) -> list[dict]:
        return [r for r in self.in_frames if r["kind"] == kind]

    # ---- 连接与握手 ----

    async def connect(self, takeover_on_conflict: bool = False,
                      timeout: float = HANDSHAKE_TIMEOUT) -> dict | None:
        """连 WS + hello 握手。返回 hello 回复；出现 conflict 且不接管时返回 None。"""
        self.ws = await websockets.connect(
            f"{self.ws_base}/ws/v1/interview/{self.sid}",
            subprotocols=["bearer." + self.token], max_size=None)
        self.hello_event.clear()
        self.conflict_event.clear()
        self.kicked_event.clear()
        self.ended_event.clear()
        self.first_asr_event.clear()
        self.closed_event.clear()
        self.reader_task = asyncio.create_task(self._reader())
        self._log("event", "connect_start", {"sid": self.sid, "client_id": self.client_id})
        await self.send_json({
            "type": "hello",
            "audio_params": AUDIO_PARAMS,
            "client_id": self.client_id,
        })
        # hello / conflict / 被关 三个出口竞速：会话已结束等错误握手不回 hello
        # 而是直接发 error 帧并关连接（调用方检查 close_code 与 error 帧）。
        # 坏 token 到不了这里——子协议鉴权在握手阶段就被拒（connect 抛 InvalidStatus）。
        done, _ = await asyncio.wait(
            [asyncio.create_task(self.hello_event.wait()),
             asyncio.create_task(self.conflict_event.wait()),
             asyncio.create_task(self.closed_event.wait())],
            timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise TimeoutError(f"{self.name}: 握手超时（hello/conflict/关闭均未到）")
        if self.closed_event.is_set():
            return None
        if self.conflict_event.is_set():
            if not takeover_on_conflict:
                return None  # 保持 pending，由调用方决定是否接管
            await self.send_json({"type": "connection.takeover"})
            await asyncio.wait_for(self.hello_event.wait(), timeout)
        return self.hello_reply

    async def _reader(self):
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                self._log("in", msg.get("type", "?"), msg)
                t = msg.get("type")
                if t == "hello":
                    self.hello_reply = msg
                    self.seq = msg.get("resume_from_seq") or 0
                    self.hello_event.set()
                elif t == "connection.conflict":
                    self.conflict_event.set()
                elif t == "connection.kicked":
                    self.kicked_event.set()
                elif t == "asr":
                    self.first_asr_event.set()
                elif t == "session.ended":
                    self.ended_event.set()
        except websockets.ConnectionClosed as e:
            close = e.rcvd or e.sent  # 收/发两侧的 Close 帧，任一侧有码即可
            self.close_code = getattr(close, "code", None)
            self.close_reason = getattr(close, "reason", None)
        except Exception as e:  # noqa: BLE001
            self.close_code, self.close_reason = None, f"reader_error: {e!r}"
        finally:
            self.closed_event.set()
            self._log("event", "reader_end", {"code": self.close_code, "reason": self.close_reason})

    # ---- 发送 ----

    async def send_json(self, obj: dict):
        self._log("out", obj.get("type", "?"), obj)
        await self.ws.send(json.dumps(obj))

    async def send_raw(self, text: str):
        """绕过 JSON 记录，直接发文本帧（构造非法输入用）。"""
        await self.ws.send(text)

    async def send_frame(self, payload: bytes, seq: int | None = None):
        if seq is None:
            seq, self.seq = self.seq, self.seq + 1
        await self.ws.send(struct.pack(">I", seq) + payload)

    async def listen_start(self):
        self.seq = 0  # 服务端 listen:start 重置 SeqTracker，客户端从 0 重新编号
        await self.send_json({"type": "listen", "state": "start"})

    async def listen_stop(self):
        await self.send_json({"type": "listen", "state": "stop"})

    async def stream(self, seconds: float, interval: float = CHUNK_INTERVAL,
                     until: asyncio.Event | None = None) -> int:
        """从音频文件头起按节拍切块推送，推满 seconds 秒或 until 置位。返回发送帧数。"""
        data = AUDIO.read_bytes()
        chunks = [data[i:i + CHUNK_BYTES] for i in range(0, len(data), CHUNK_BYTES)]
        # 时长测量用单调钟（不受系统校时/跳变影响）；日志时间戳才用墙钟
        n, t_end = 0, time.monotonic() + seconds
        self._log("event", "stream_start", {"seconds": seconds, "chunks": min(len(chunks), int(seconds / interval) + 1)})
        try:
            for c in chunks:
                if until and until.is_set():
                    break
                if time.monotonic() >= t_end:
                    break
                try:
                    await self.send_frame(c)
                except websockets.ConnectionClosed:
                    self._log("event", "stream_aborted", {"sent": n, "why": "ws closed"})
                    return n
                n += 1
                await asyncio.sleep(interval)
        finally:
            self._log("event", "stream_end", {"sent": n})
        return n

    # ---- 断开与收尾 ----

    async def raw_disconnect(self):
        """裸断：不发 listen:stop、不发 close code，直接断 TCP（模拟断网）。"""
        self._log("event", "raw_disconnect", {})
        try:
            self.ws.transport.abort()
        except Exception:  # noqa: BLE001
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def wait_closed(self, timeout: float = 10) -> bool:
        """等服务端关闭；返回是否在超时内关闭。结果见 close_code/close_reason。"""
        if self.reader_task:
            try:
                await asyncio.wait_for(asyncio.shield(self.reader_task), timeout)
            except asyncio.TimeoutError:
                return False
        return self.close_code is not None or self.close_reason is not None

    async def wait_first_asr(self, timeout: float = ASR_DEADLINE_S) -> dict | None:
        """等第一条 asr 段到达，返回该帧。超时（默认 ASR_DEADLINE_S）返回 None，
        不抛——避免 ASR 挂死时整个用例挂在 `await` 上。代替硬编码 50/70/90s sleep。
        """
        try:
            await asyncio.wait_for(self.first_asr_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        for r in self.in_frames:
            if r["kind"] == "asr":
                return r
        return None

    async def close(self):
        if self.ws:
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self.reader_task:
            try:
                await asyncio.wait_for(self.reader_task, 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.reader_task.cancel()
        if self._f:
            self._f.close()


class E2EApi:
    """REST 侧：登录 + 访谈 CRUD。token 惰性获取、失效自动重登。"""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token: str | None = None

    async def _client(self, timeout: float = 15) -> httpx.AsyncClient:
        """httpx 客户端。默认 15s 普通接口；DELETE 走 end() 终算 LLM 可能
        接近 60s 上限，建议调用方按需显式传更长 timeout，避免被 httpx
        截断而被误读为「删除失败」（实则是终算 LLM 跑完了）。
        """
        return httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def _auth_headers(self) -> dict:
        if self.token is None:
            async with await self._client() as c:
                r = await c.post("/api/v1/auth/login",
                                 json={"username": self.username, "password": self.password})
                r.raise_for_status()
                self.token = r.json()["access_token"]
        return {"Authorization": f"Bearer {self.token}"}

    async def create_interview(self, title: str, goal: str) -> str:
        async with await self._client() as c:
            r = await c.post("/api/v1/interviews", headers=await self._auth_headers(),
                             json={"template_id": TEMPLATE_ID,
                                   "base_info": {"title": title, "project": "E2E测试", "interviewee": "测试对象"},
                                   "goal": goal})
            r.raise_for_status()
            return r.json()["id"]

    async def end_interview(self, sid: str) -> tuple[int, str]:
        async with await self._client() as c:
            r = await c.post(f"/api/v1/interviews/{sid}/end", headers=await self._auth_headers())
            return r.status_code, r.text[:200]

    async def patch_interview(self, sid: str, body: dict) -> tuple[int, str]:
        """PATCH /interviews/{sid}：编辑 base_info / goal。返回 (状态码, body 节选)。"""
        async with await self._client() as c:
            r = await c.patch(f"/api/v1/interviews/{sid}", headers=await self._auth_headers(),
                              json=body)
            return r.status_code, r.text[:200]

    async def delete_interview(self, sid: str, timeout: float = 90) -> tuple[int, str]:
        """DELETE /interviews/{sid}：删除访谈。进行中/连接中拒（409），其他态成功。

        默认 timeout=90s：源码对仍寄存的 runtime 会同步 await runtime.end()
        （含终算 LLM，上限 60s）+ 拆 ASR + 落盘，常规用 15s httpx 超时会被
        截断误报失败。可按需要再放宽到 120s。
        """
        async with await self._client(timeout=timeout) as c:
            r = await c.delete(f"/api/v1/interviews/{sid}", headers=await self._auth_headers())
            return r.status_code, r.text[:200]

    async def put_config(self, group: str, body: dict) -> tuple[int, str]:
        """admin: PUT /admin/config/{group}：运营可调配置（session.max_concurrent 等）。"""
        async with await self._client() as c:
            r = await c.put(f"/api/v1/admin/config/{group}",
                            headers=await self._auth_headers(), json=body)
            return r.status_code, r.text[:200]

    async def get_interview(self, sid: str) -> dict:
        async with await self._client() as c:
            r = await c.get(f"/api/v1/interviews/{sid}", headers=await self._auth_headers())
            r.raise_for_status()
            return r.json()

    async def list_interviews(self, status: str | None = None) -> dict:
        """列访谈（按状态过滤可选）。返回 {"items": [...]}。"""
        params = {"status": status} if status else None
        async with await self._client() as c:
            r = await c.get("/api/v1/interviews", params=params,
                            headers=await self._auth_headers())
            r.raise_for_status()
            return r.json()

    async def get_report(self, sid: str) -> dict:
        """取报告。首访触发 LLM 生成，耗时可达分钟级，须用长超时。"""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=300) as c:
            r = await c.get(f"/api/v1/interviews/{sid}/report", headers=await self._auth_headers())
            r.raise_for_status()
            return r.json()

    async def export_report(self, sid: str, fmt: str = "md") -> tuple[int, bytes]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60) as c:
            r = await c.post(f"/api/v1/interviews/{sid}/export?format={fmt}",
                             headers=await self._auth_headers())
            return r.status_code, r.content


# ---- 结构不变量断言辅助 ----

def check_frame_invariants(frames: list[dict], name: str = "") -> list[str]:
    """检查一个客户端收到的帧流，返回违规列表（空 = 通过）。

    - asr 段 seg_id 严格递增（s1→s2→…，回退 = 转写错乱）
    - coaching.update 的 version 不回退（recomputing 中间态除外）
    - 清单项状态不出现 done → todo/doing 闪烁回退
    - 不应出现 error 帧
    """
    problems: list[str] = []
    last_seg, last_version = -1, -1
    status_mem: dict[str, str] = {}
    for r in frames:
        d, k = r.get("data") or {}, r.get("kind")
        if k == "asr":
            # 解析失败即视为违规：格式变更后这里会主动爆出来，而不是悄悄
            # 把"递增/无空洞"两条断言跳过去。前端/后端任何一方改 seg_id
            # 都得先来同步这个正则。
            sid = _parse_seg_id(d.get("seg_id"), f"{name}.asr")
            if sid <= last_seg:
                problems.append(f"{name}: asr seg_id 回退 s{last_seg}→s{sid}")
            last_seg = max(last_seg, sid)
        elif k == "coaching.update":
            v = d.get("version", 0)
            if d.get("phase") != "recomputing":
                if v < last_version:
                    problems.append(f"{name}: coaching version 回退 {last_version}→{v}")
                last_version = max(last_version, v)
            for it in d.get("items") or []:
                iid, st = it["id"], it.get("status")
                if status_mem.get(iid) == "done" and st not in ("done", "skipped", "ignored"):
                    problems.append(f"{name}: item {iid} done→{st} 回退闪烁 @v{v}")
                status_mem[iid] = st
        elif k == "error":
            problems.append(f"{name}: 收 error 帧 {d}")
    return problems


def _parse_seg_id(raw, where: str) -> int:
    """把 seg_id 解析成正整数；解析失败抛 AssertionError（不变量检查器约定）。"""
    m = _SEG_RE.match(str(raw or ""))
    assert m, f"{where}: seg_id 解析失败（格式变更？）：{raw!r}"
    return int(m.group(1))


def check_interview_data(info: dict, name: str = "") -> list[str]:
    """检查 REST 查询到的会话落库数据，返回违规列表（空 = 通过）。

    - 转写 seg_id 无空洞、无空文本段
    - coaching items id 不重复；coverage 引用的 seg 均存在
    - 已结束的访谈清单不为空
    """
    problems: list[str] = []
    transcript = info.get("transcript") or []
    items = info.get("items") or []
    coverage = info.get("coverage") or []

    seg_ids: list[int] = []
    for seg in transcript:
        # 解析失败直接挂：seg_id 格式变了必须显式同步，不允许静默跳过
        seg_ids.append(_parse_seg_id(seg.get("seg_id"), f"{name}.transcript"))
        if not (seg.get("text") or "").strip():
            problems.append(f"{name}: 空文本段 {seg.get('seg_id')}")
    nums = list(seg_ids)
    if nums:
        gaps = [i for i in range(nums[0], nums[-1] + 1) if i not in set(nums)]
        if gaps:
            problems.append(f"{name}: seg_id 空洞 {gaps[:10]}")

    if len(items) != len({it.get("id") for it in items}):
        problems.append(f"{name}: coaching items id 重复")
    if info.get("status") == "ended" and not items:
        problems.append(f"{name}: 已结束但清单为空")

    valid = {f"s{n}" for n in nums}
    for c in coverage:
        if isinstance(c, dict):
            bad = set(c.get("seg_ids") or c.get("segs") or []) - valid
            if bad:
                problems.append(f"{name}: coverage 引用不存在 seg {sorted(bad)[:10]}")
    return problems

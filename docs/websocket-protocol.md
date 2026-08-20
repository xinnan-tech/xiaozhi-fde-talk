# WebSocket 通信协议

小智方糖访谈页面的实时通道协议。前端按本协议即可与后端完成：连接握手 → 开麦上行音频 → 接收实时转写与辅导清单 → 处理重连/接管 → 结束访谈。

服务端实现：`backend/app/transport/websocket/`。本协议只描述 wire 格式与状态机，不涉及 LLM/ASR 内部。

---

## 1. 端点

```
ws://{host}:{port}/ws/v1/interview/{interview_id}
```

| 项 | 值 |
| --- | --- |
| 路径前缀 | `/ws/v1` |
| 子协议 | 鉴权用 `bearer.<jwt>`，见 §3 |
| 单帧大小上限 | 64 KiB，服务端硬编码，不开放配置（超出即拒并关连接） |
| 握手超时 | 5 s 内未发首条 `hello` 即拒 |
| 默认端口 | 8000 |

`interview_id` 必须存在且属于当前登录用户；否则握手失败（4404）。

---

## 2. 鉴权

token 只通过 `Sec-WebSocket-Protocol` 子协议传递：

```
new WebSocket(url, ["bearer." + jwt])
```

服务端在 accept 之前校验 token；缺失或无效 → 握手被拒（客户端收到 HTTP 403，`onerror`/`onclose` 触发，收不到任何 WS 帧）。URL 与 hello 消息体都不带 token。

---

## 3. 握手

**首条消息必须是 hello，且必须在 5 s 内到达。**

客户端 → 服务端：

```json
{
  "type": "hello",
  "client_id": "uuid-or-any-stable-id",
  "audio_params": {
    "format": "opus",
    "sample_rate": 16000,
    "channels": 1,
    "frame_duration": 60
  }
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `type` | 是 | 固定 `"hello"`（消息体不携带会话 id，会话只由 URL 路径决定） |
| `client_id` | 强烈建议 | 同标签/同设备保持不变（用 `sessionStorage`），不同标签/不同设备必须不同。用于区分「同端断线重连」与「另一端竞争接管」（见 §6）。**不带则每次连接随机生成新身份**：与旧连接并存（旧连接仍在线，或断线后其拆除尚未完成）时，本端会被当作另一端触发 `connection.conflict` 接管弹框；旧连接已断开后再连，仍走存活窗口无缝复用，不弹冲突。带稳定 `client_id` 时，并存竞态窗口内的同端重连也能被静默复用 |
| `audio_params` | 否 | 透传给服务端，会在握手回包中原样回显（接管路径的 hello 除外，恒为 `{}`）。当前版本服务端仅记录、不校验 |
| `protocol_version` | 否 | 客户端协议版本，当前为 1；服务端不校验，回包中回显服务端版本 |

服务端 → 客户端（握手成功）：

```json
{
  "type": "hello",
  "session_id": "abc",
  "audio_params": { ... 同上 ... },
  "protocol_version": 1,
  "resume_from_seq": 42
}
```

| 字段 | 说明 |
| --- | --- |
| `type` | 固定 `"hello"` |
| `session_id` | 回显 |
| `audio_params` | 原样回显，接管路径恒 `{}`；完整取值示例见 §11，两处须同步改 |
| `protocol_version` | 服务端协议版本 |
| `resume_from_seq` | 客户端下一个音频帧应使用的起始 seq。重连场景会 >0；首连为 0 |

**注意**：握手回 `hello` 后，服务端会接着推送已缓冲的辅导 snapshot（一条 `coaching.update`，phase=final），表示「当前该问什么」。客户端必须准备好接收。

握手成功后该连接进入「已绑定」状态，可发音频和指令。

### 3.1 协议版本与演进

`protocol_version` 当前为 `1`。服务端只实现当前版本，不做多版本软兼容；不兼容变更
随版本号 +1 发布，接入方随服务端升级。客户端 hello 中的 `protocol_version` 仅作
诊断信息上报，服务端不据此分支。

---

## 4. 音频帧

**二进制帧**。格式：

```
┌────────────────────────────┬──────────────────────────┐
│  seq (4 B, big-endian u32) │  opus payload            │
└────────────────────────────┴──────────────────────────┘
```

- `seq` 从客户端 0 开始递增。
- 重连且未重新开麦时，**从 `resume_from_seq` 起续编**（见 §6.1）。
- 每次「开麦」都应**从 0 重新编 seq**（重建 `MediaRecorder` 时旧流无法续号）。服务端在收到 `listen:start` 时会重置去重窗口，已发送过的低 seq 会被丢弃。
- 整帧（4 字节 seq 头 + opus payload）总长不得超过 §1 的 64 KiB 单帧上限。
- 不足 4 字节（放不下 seq 头）的帧被服务端静默丢弃。

---

## 5. 消息总览

### 5.1 客户端 → 服务端（文本 JSON）

| `type` | 必填字段 | 作用 |
| --- | --- | --- |
| `hello` | — | 仅在握手首次需要，之后再发等同 noop（字段见 §3） |
| `listen` | `state`: `"start"` \| `"stop"` | 开麦 / 停麦。state 仅接受 "start" / "stop"，未知值被忽略并记日志 |
| `coaching.skip` | `id`: string | 把该辅导项标记为「本次跳过」，不再出现在「待问」列表 |
| `coaching.ignore` | `id`: string | 标记为「已忽略」，彻底不再展示 |
| `connection.takeover` | — | 仅在「pending」状态可发，见 §6 |
| `session.touch` | — | keepalive：只重置空闲看门狗的活跃时间戳，**无任何副作用**（不重启 ASR / 不重算辅导 / 不发帧）。可用于客户端「我还在，我不要被挂起」按钮，不与 §6 重连路径冲突。协议层于 7833a58 后已支持；当前 `frontend/` Vue 工程尚未发送本帧——15faa0a 曾把等价 `keepAlive()` + idle-warning toast 接入到 **已废弃的** `backend/static/index.html`（dev 模式不再 serve、Docker 部署会被 `frontend/dist` 整目录覆盖），前端接入需要独立 PR |

未列出的 `type` 会被服务端忽略并打一条 warning，不影响连接。已列出但前端尚未接入的（如 `session.touch`）同样会被服务端接受并执行预期行为——前端接入时无须修改协议约定。

### 5.2 服务端 → 客户端（文本 JSON）

| `type` | 含义 | 见 |
| --- | --- | --- |
| `hello` | 握手/接管成功回包 | §3、§6 |
| `connection.conflict` | 已有别的 owner 在连接，本端进入 pending | §6 |
| `connection.kicked` | 本端被另一端接管 | §6 |
| `asr` | 一段转写结果（增量） | §7 |
| `coaching.update` | 辅导清单变更（首算 / 事件驱动重算 / 重连 snapshot） | §8 |
| `session.ended` | 会话已结束（REST end 后对在线端的兜底通知），紧接 4406 关闭 | §9、§10 |
| `session.suspended` | 会话空闲超时被挂起（可继续），紧接 4403 关闭 | §9 |
| `audio.low_level` | 开麦周期内持续极低电平提示（每周期至多一次），不关闭连接 | |
| `error` | 错误通告，是否关闭连接见 §9 | §9 |

载荷字段（仅列有载荷的帧，`error` 见 §9、`asr` 见 §7、`coaching.update` 见 §8）：

- `hello`：`session_id` / `audio_params` / `protocol_version` / `resume_from_seq`（§3）。
- `connection.conflict`：`message`（string）— 给用户看的提示文案。
- `connection.kicked`：`reason`（string）— 被踢原因文案。
- `session.ended`：`session_id`（string）。
- `session.suspended`：`session_id`（string）。
- `audio.low_level`：`dbfs`（number，30s 滑窗（攒满 20s 即判）的 p95，单位 dBFS）/ `message`（string）— 提示文案。触发条件：p95 < -40 dBFS 且窗内有语音动态（p95−p10 > 15dB，排除纯停顿/环境噪声）；与客户端 AGC 分层——AGC 保可识别下限，本帧兜底 AGC 救不回的场景（系统输入音量近零/浏览器无 AGC/超出最大增益）。每个开麦周期（`listen:start` 之间）至多一帧；连接保持不变。
- `error`：`type`（固定 `"error"`）/ `code`（string wire code，见 §9 表）/ `message`（string，本地化文案，回退到 code 本身）/ `i18n_key`（string，从语种目录查表，前端用此字段调用本地化）/ `i18n_params`（object，渲染模板时需要的命名参数；前置 i18n 化落地）/ `close`（number，RFC6455 关闭码；**仅在服务端会同时关闭本连接时存在**）。完整示例与 code 全集见 §9。

---

## 6. 重连 / 续传 / 接管

服务端在 WS 断开时**不会**结束访谈会话。运行时会进入「存活窗口」（默认 60 s，由配置 `session.liveness_window_s` 决定）。窗口内重连可复用同一份运行时（管线、辅导引擎、已落盘状态都不重建）。

### 6.1 客户端断开 → 自动重连

客户端断线后建议立即（同标签刷新 / 切网）重连，重连 hello 中带**原 `client_id`**：

1. 服务端识别为同身份 → 静默复用运行时。
2. 回 `hello` 的 `resume_from_seq` 是已喂给 ASR 的下一帧号。
3. 之后的 seq 编号取决于客户端如何恢复录音：
   - **录音未中断**（闪断、未重建 `MediaRecorder`、不发 `listen:start`）：把本地 seq 置为
     `resume_from_seq` 续编，服务端按会话级去重窗口收帧。
   - **重新开麦**（重建 recorder、发 `listen:start`）：seq 从 0 重新编起。服务端收到
     `listen:start` 会整体重置去重窗口，旧窗口的高水位作废。
   浏览器断线后 recorder 通常已失效，走第二条路径是常态；`resume_from_seq` 仅在第一条
   路径（连接层闪断但音频流仍连续）时有意义。
4. 服务端还会重推一条 `coaching.update{final}` 作为 snapshot。断连期间缓冲的 critical 通知（`error`、`session.ended`）也会在 hello 后重放。

### 6.2 客户端断开 → 重连超时

存活窗口到期，服务端会：

1. 标记 runtime 为正在销毁（重连中会得到 4406 `session_ended`）。
2. 关闭 ASR 连接、强制落盘转写、释放辅导引擎。
3. 此时客户端再连会被拒（4406），需要新建访谈。

### 6.3 连接竞争 → 接管（不同 client_id）

同一访谈只允许一个 owner 处于「活跃」状态。

时序：

```
A 端                          服务端                     B 端
│  hello (client_id=A)  ───► │                          │
│ ◄─── hello (owner)         │                          │
│   ... 收发音频 ...          │                          │
│                            │ ◄── hello (client_id=B) │
│                            │ ── connection.conflict ─►│   ← B 是 pending，未 hello
│                            │                          │  ← B 决定：
│                            │                          │     "接管" → 发 connection.takeover
│                            │                          │     "取消" → 关 WS（不报错）
│ ◄─── connection.kicked     │ ◄── connection.takeover  │
│                            │ ── hello ────────────────►│   ← B 变 owner
│  WS 关(4402)                │                          │
```

**关键点**：

- 收到 `connection.conflict` 时连接**未 hello**，仍可发 `connection.takeover`。
- pending 期间，**除 `connection.takeover` 外的所有入站（音频、listen、coaching.*）都会被服务端忽略**。
- 收到 `connection.kicked` 后：本端必须停麦、不重连、回到「可继续访谈」等待用户再次操作。
- 同 `client_id` 的并发连接不算竞争：会被视为「同端断线重连」静默复用。
- 接管成功后服务端**先推一条 `coaching.update{final}` snapshot、再回 `hello`**（与首连顺序相反）；该 hello 的 `audio_params` 恒为 `{}`，`resume_from_seq` 语义不变。

### 6.4 pending 连接断线

服务端无副作用，原 owner 不变。

---

## 7. 转写（asr）

服务端在流式 ASR 产出一句后推送：

```json
{
  "type": "asr",
  "seg_id": "12",
  "start_ms": 1840,
  "speaker": "unknown",
  "text": "我们这边主要做的是 …",
  "final": true
}
```

| 字段 | 说明 |
| --- | --- |
| `type` | 固定 `"asr"` |
| `seg_id` | 客户端去重用，建议按值排版去重 |
| `start_ms` | 该段在录音中的起始偏移（毫秒） |
| `speaker` | 说话人标签；当前版本恒为 `"unknown"`，预留字段 |
| `text` | 该段转写文本 |
| `final` | `true` = 终结句；`false` = 中间结果（可被后续覆盖），客户端可选择不渲染 |

asr 推送频率由服务端 ASR 断句策略决定，客户端无法控制。`final=true` 的句不会撤销。

---

## 8. 辅导清单（coaching.update）

推送时机：

1. 首次绑定 → 立即推一条 `phase=final`（当前清单：模板 must_ask，或已生成的首评定制清单）。
   首评 = 结合访谈对象/背景/目标用 LLM 定制的第一批问题，可提前经
   `POST /api/v1/interviews/{interview_id}/first-batch` 触发（幂等，失败可重试）；
   若绑定时尚未生成且没有对话记录，服务端会在绑定后后台补跑一次
   （客户端先收到种子清单，随后照常收到 `recomputing` → `final`）。
2. 之后**事件驱动**触发 LLM 重算：新转写句后静默满 `coach.pause_s`（默认 5 s，停顿防抖）或未消费新段达 `coach.max_pending_segments`（默认 8，连续说话兜底）即触发；两次重算间隔不小于 `coach.min_interval_s`（默认 10 s，兼失败退避）。`listen:stop` 收尾时若窗口非空也会补一次重算。重算期间先发 `recomputing` 占位，再发 `final` 结果。LLM 失败或超时（`coach.llm_timeout_s`，默认 45 s）会保留上一份并仍发 `final`。
3. 重连（§6）→ 重推一条 `phase=final` 作为 snapshot（不递增 version）。

消息载荷：

```json
{
  "type": "coaching.update",
  "phase": "final",
  "version": 3,
  "items": [
    {
      "id": "objective",
      "text": "本次访谈要达成的目标是什么？",
      "status": "todo",
      "reason": "",
      "priority": 1,
      "desc": "目的与衡量标准"
    }
  ],
  "skipped_ack": []
}
```

`phase`：

| 值 | 含义 | 客户端处理建议 |
| --- | --- | --- |
| `recomputing` | LLM 在算，下方 `items=[]` | 展示「正在思考」占位，**不要清空现有清单** |
| `final` | 新清单可用 | 整体替换当前清单 |

`status`：

| 值 | 含义 |
| --- | --- |
| `todo` | 待问 |
| `new` | 新冒出的必问项 |
| `done` | 已问清 |
| `skipped` | 本次跳过（由客户端 `coaching.skip` 产生） |
| `ignored` | 已忽略（由客户端 `coaching.ignore` 产生） |

`skipped_ack` 当前始终为空数组；保留字段。

---

## 9. 错误与关闭

服务端用 `error` 帧通告错误；除 `asr_unavailable` 的会话中场景（见下）外，发帧后紧接关闭连接：

```json
{ "type": "error", "code": "asr_unavailable", "i18n_key": "ws.asr.connect_fail", "i18n_params": {}, "message": "语音识别连接已断开" }
```

关闭前还可能推两类通知帧（不是 `error`）：`session.ended`（REST end 后对在线端的兜底通知）和 `session.suspended`（空闲挂起）。

收到 `error` 后**不应自动重连**——通常意味着服务端或依赖（ASR/LLM）已不可用，重连无意义。

`error` 帧的 `code` 全集：

| `code` | 含义 | 是否关连接 |
| --- | --- | --- |
| `bad_handshake` | 首条消息不是 JSON / 不是 hello | 是（4000） |
| `bad_json` | 文本帧不是合法 JSON | 是（4411） |
| `handshake_timeout` | 5 s 内未收到 hello | 是（4408） |
| `not_found` | 访谈不存在或不属于当前用户 | 是（4404） |
| `session_ended` | 会话已结束 / 存活窗口已过 | 是（4406） |
| `concurrent_limit` | 活跃访谈达上限 | 是（4409） |
| `frame_too_large` | 单帧超过 64 KiB | 是（4410） |
| `internal` | 服务端内部错误（详情只进日志） | 是（4000） |
| `asr_unavailable` | 语音识别不可用，**两种场景见下** | 建立失败：是（4000）；流中断连：**否** |

**`asr_unavailable` 的两种场景**：

- **建立阶段**（`listen:start` 首次建 ASR 管线时连接失败）：error 帧后连接以 4000 关闭。
  客户端提示用户稍后重试（重连即可重新建管线）。
- **会话中**（ASR 流中途断开）：**仅发 error 帧，连接保留**。服务端已将管线标记失效，
  客户端重新发送 `{"type":"listen","state":"start"}` 会强制重建管线并恢复转写，无需断开重连。

两种场景共用同一 `code`（不拆分）；客户端以「error 帧之后连接是否被关闭」区分——
未关闭即按第二种场景处理，直接重发 `listen` `state:"start"`。

连接关闭码：

| 关闭码 | 含义 | 客户端处理 |
| --- | --- | --- |
| `1000` | 正常关闭 | — |
| `4000` | 通用 / 内部错误 | 检查 `error` 帧 |
| `4402` | 被另一端接管（§6） | 提示用户，回到列表 |
| `4403` | 空闲挂起：关闭前先收 `session.suspended` 帧（可继续） | 提示用户，可从列表重新进入 |
| `4404` | `not_found` 访谈不存在或不属于当前用户 | 提示用户，回到列表 |
| `4406` | `session_ended` 访谈已结束 / 存活窗口已过（REST end 场景关闭前先收 `session.ended` 帧） | 提示用户，新建访谈 |
| `4408` | `handshake_timeout` 5 s 内未发 hello | 检查客户端实现 |
| `4409` | `concurrent_limit` 活跃访谈达上限 | 关掉其他访谈 |
| `4410` | `frame_too_large` 单帧 > 64 KiB | 检查音频帧大小 |
| `4411` | `bad_json` 文本帧不是合法 JSON | 检查客户端实现 |

---

## 10. 结束访谈

**会话状态归 HTTP 管，不走 WS。**

```
POST /api/v1/interviews/{interview_id}/end
Authorization: Bearer <jwt>
```

服务端立即把状态写盘为 `ended` 并返回 200；runtime 的收尾（coaching 最终重算，LLM 上限 60 s）在后台异步执行，不阻塞响应。

客户端在 200 之后应：

1. 停麦（`mr.stop()`）。
2. 主动 `ws.close()` 关闭连接。若不关，后台拆除完成后服务端会兜底推 `session.ended` 并以 4406 关闭。
3. 禁用「继续访谈 / 暂停麦 / 结束访谈」，启用「查看报告 / 导出」。

---

## 11. 最小接入示例

伪代码（浏览器）：

```js
const ws = new WebSocket(`${WS}/ws/v1/interview/${sid}`, [`bearer.${token}`]);
ws.binaryType = "arraybuffer";

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "hello",
    client_id: getClientId(),          // sessionStorage 持久化
    audio_params: { format: "opus", sample_rate: 16000, channels: 1, frame_duration: 60 },
    protocol_version: 1,
  }));
};

ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  switch (msg.type) {
    case "hello":            seq = msg.resume_from_seq || 0; startMic(); break;
    case "asr":              appendTranscript(msg); break;
    case "coaching.update":  renderCoaching(msg); break;
    case "connection.conflict": showTakeoverDialog(msg.message); break;
    case "connection.kicked":  onKicked(msg.reason); break;
    case "error":            showFatal(msg.message); break;
  }
};

// 上行音频
function sendAudio(pcmPayload) {
  const buf = new Uint8Array(4 + pcmPayload.byteLength);
  new DataView(buf.buffer).setUint32(0, seq, false);   // big-endian
  buf.set(new Uint8Array(pcmPayload), 4);
  ws.send(buf);
  seq++;
}

// 开麦 / 停麦
ws.send(JSON.stringify({ type: "listen", state: "start" }));
ws.send(JSON.stringify({ type: "listen", state: "stop" }));

// 辅导项动作
ws.send(JSON.stringify({ type: "coaching.skip", id: "pain" }));
ws.send(JSON.stringify({ type: "coaching.ignore", id: "constraints" }));

// 接管（pending 状态专属）
ws.send(JSON.stringify({ type: "connection.takeover" }));
```

---

## 12. 常见问题

**Q: 收到 `connection.conflict` 怎么处理？**
A: 弹框问用户。同意 → 发 `connection.takeover`；取消 → 直接 `ws.close()`，无副作用。

**Q: 断网几秒后回来，重连还是 4406？**
A: 已超过存活窗口（默认 60 s），会话被服务端自动收尾。让用户回列表刷新状态。

**Q: 重连后音频进得来却不出字？**
A: 重建 `MediaRecorder`（`mr.stop()` → `new MediaRecorder(...)`），必须发一条**含 EBML 头**的全新流。直接 `resume()` 旧 recorder 会发无头续流污染解码器。

**Q: `seq` 是会话级还是连接级？**
A: 服务端会话级单调递增，跨连接保留。客户端每次 `listen:start` 都从 0 起编（因为 MediaRecorder 被重建）；重连时按服务端回包的 `resume_from_seq` 续编。重连后若需重新开麦（发 `listen:start`），seq 直接从 0 编起，无需理会 `resume_from_seq`（见 §6.1）。

**Q: 同一会话在两个浏览器标签打开会怎样？**
A: 第二个标签收到 `connection.conflict`，弹「接管」框。接管后第一个标签收 `connection.kicked` 并被强制断开（4402）。

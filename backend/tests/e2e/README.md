# E2E 混沌测试

黑盒端到端测试：对运行中的 8000 端口后端服务发真实请求（HTTP + WS），推真实访谈录音
（`audio/interview.webm`，9m16s），走通真实 ASR / LLM / SQLite 全链路。与
`tests/unit`（mock）、`tests/integration`（进程内 + mock 模型）互补。

## 运行

```bash
cd backend
python -m pytest -m e2e tests/e2e                   # 全量（约 10-15 分钟，消耗真实 LLM token）
python -m pytest -m e2e tests/e2e/test_takeover.py  # 单文件
```

日常 `pytest` 不会跑这组（pytest.ini 默认 `-m "not e2e"`）。后端不可达时整组自动跳过。

## 前置条件

1. 后端已启动且能登录（在 `backend/` 目录下启动，否则 `.env` 不生效）：
   ```bash
   cd backend && python -m app.main
   ```
2. 后端配置了可用的真实 ASR（FunASR）和 LLM。ASR 不可达时推流用例会因
   "未收到 asr 段" 失败——那是环境问题，不是代码问题。
3. 内存/泄漏用例（`test_leak.py`）额外需要后端进程号：
   ```bash
   E2E_BACKEND_PID=$(lsof -ti:8000 -sTCP:LISTEN) python -m pytest -m e2e tests/e2e/test_leak.py
   ```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `E2E_BASE_URL` | `http://127.0.0.1:8000` | 后端地址 |
| `E2E_USERNAME` / `E2E_PASSWORD` | `admin` / `admin` | 登录账号（首位注册的用户为超级管理员；启动后到登录弹窗点"去注册"创建首位用户即可） |
| `E2E_BACKEND_PID` | 无 | 后端进程号；不设则跳过泄漏用例 |
| `E2E_ASR_ADDR` | `100.79.27.90:10096` | FunASR 的 host:port，残留连接检查用，按实际部署覆盖 |

### pytest 选项

| 选项 | 默认 | 说明 |
|---|---|---|
| `--rss-budget-kb` | `30720`（30MB） | `test_leak` 用例允许的单轮 RSS 增长（KB）。30MB 依据：Python 内存池不还 OS，RSS 小额抬升是正常的；只拦每轮几十 MB 级的灾难性泄漏，小额靠残留连接兜底。大并发部署可放宽到 `102400`（100MB）。 |

### 环境冒烟

修过 `_smoke_count_asr.py` 的 `count_asr_connections`（lsof 参数：`-a` AND 交集、`-iTCP@ADDR` 地址过滤、`parts[1]` PID 列）后，最好先跑一次直冒烟验证，避免假绿再走全套 e2e：

```bash
python3 tests/e2e/_smoke_count_asr.py
# 期望：[smoke] PASS —— -a / 列号 / 地址过滤 三件套联动验证
```

失败则说明 lsof 仍需复核，不是真修好。

## 用例一览

| 文件 | 覆盖 |
|---|---|
| `test_smoke.py` | 主链路：握手 → 推流出转写 → REST 结束收 `session.ended` + 关闭码 4406；结束后拒绝重连 |
| `test_takeover.py` | 多标签抢同一会话：`connection.conflict` 提示 → takeover 接管 → 旧端 `connection.kicked` + 4402；pending 连接的幽灵帧被丢弃；同 client_id 重连不算竞争 |
| `test_reconnect.py` | 断网裸断 → 宽限窗内重连 → 转写 seg_id 跨窗口连续 |
| `test_stress.py` | 3 路并发推流；麦克风开关循环；暴力输入（>64KB 帧 4410、坏 JSON、未知类型、坏 token 握手拒 401/403） |
| `test_operations_patch_delete.py` | REST 写路径：PATCH on created/suspended 200、in_progress 409；DELETE on suspended/ended 200、in_progress 409；suspended 删除复活防御（liveness 到期 GET 仍 404）；PATCH 寄存-重连不回滚（命中 _refresh_session_fields） |
| `test_concurrency_limit.py` | 顶到 `session.max_concurrent` 时 SUSPENDED→IN_PROGRESS 恢复被 4409 + concurrent_limit 拒（与并发压力 3 路相区别——补源码专门防御分支） |
| `test_edges.py` | 握手超时（4408）；重复 hello 不污染 seq；接管后旧 owner 残留帧被 ownership 守卫挡在外 |
| `test_leak.py` | 每轮会话结束后到 FunASR 的连接数归零（连接泄漏回归）；多轮 RSS 增长有界 |

## 断言的协议不变量

`chaos.py` 里的两个检查器是全部用例共用的"结构不变量"：

- `check_frame_invariants`（帧流）：asr 段 seg_id 严格递增；coaching.update 的
  version 不回退（recomputing 中间态除外）；清单项不出现 done→todo 闪烁；无 error 帧
- `check_interview_data`（REST 落库）：转写 seg_id 无空洞、无空文本段；items id
  不重复；coverage 引用的 seg 均存在；已结束会话清单非空

每次运行的全部双向帧流水写在 pytest 临时目录 `<name>.jsonl`（测试失败时路径会出现在
fixture 信息里），可事后离线排查。

## 加新用例

复用 `chaos.ChaosClient`（一个实例 = 一个 WS 连接，支持 conflict/takeover/裸断/推流）
与 `chaos.E2EApi`（REST 封装），fixture 见 `conftest.py`（`api` / `new_sid` /
`make_client`）。给测试打 `@pytest.mark.e2e` 即可。

"""E2E 测试公共 fixture。

本模块同时承载两套不重叠的 fixture：

1. 混沌 E2E（`pytest -m e2e`）
   - BASE_URL 默认 http://127.0.0.1:8000（独立 session，靠 E2E_BASE_URL 覆盖）
   - 提供 api / logdir / backend_pid / rss_budget_kb / make_client / new_sid 等
   - 后端离线时整组通过 pytest_collection_modifyitems 自动跳过

2. Playwright 后台 API 辅助（`from tests.e2e.conftest import admin_token` 等）
   - PLAYWRIGHT_BASE_URL 默认 http://127.0.0.1:8001（前端 webServer 起的 uvicorn）
   - 仅备 admin token / headers，进程生命周期由 Playwright 接管
   - 复用 `tests.conftest._TEST_ADMIN_PASSWORD`，不重新定义常量
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

import httpx
import pytest

from chaos import E2EApi

# 复用的既有常量（admin 路径用，避免与既有 conftest 漂移）
from tests.conftest import _TEST_ADMIN_PASSWORD

# --- 混沌 E2E 默认（8000，独立 session）-----------------------------------
BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000")
USERNAME = os.environ.get("E2E_USERNAME", "admin")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin")
# 内存泄漏用例：本机后端进程 PID（RSS / 残留连接检查需要）；不设则跳过
BACKEND_PID = os.environ.get("E2E_BACKEND_PID", "")
# 后端连接的 FunASR 地址 host:port（残留连接检查用），按实际部署覆盖
ASR_ADDR = os.environ.get("E2E_ASR_ADDR", "100.79.27.90:10096")

# --- Playwright admin 辅助默认（8001，前端 webServer 起的 uvicorn）----------
PLAYWRIGHT_BASE_URL = os.environ.get(
    "PLAYWRIGHT_E2E_BASE_URL", "http://127.0.0.1:8001"
)


def _probe_backend() -> str | None:
    """后端不可达时返回原因（None = 可用）。

    用同步 httpx 探测：避免 asyncio.run 在已经有事件循环的环境（如 pytest-asyncio
    inline mode / IDE runner）下抛 "already running" 之类的脆弱边界。
    """
    try:
        with httpx.Client(base_url=BASE_URL, timeout=5) as c:
            r = c.post("/api/v1/auth/login",
                       json={"username": USERNAME, "password": PASSWORD})
            r.raise_for_status()
        return None
    except Exception as e:  # noqa: BLE001
        return f"E2E 后端不可用（{BASE_URL}）：{e}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """后端离线时跳过全部 e2e 用例，避免误报。"""
    e2e_items = [i for i in items if i.get_closest_marker("e2e")]
    if not e2e_items:
        return
    reason = _probe_backend()
    if reason:
        for item in e2e_items:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def api() -> E2EApi:
    return E2EApi(BASE_URL, USERNAME, PASSWORD)


@pytest.fixture(scope="session", autouse=True)
def _enable_stub_llm():
    """激活后端 llm.type=stub，避免 e2e 用例依赖真实 LLM API key。

    后端在 backend/app/adapters/llm/stub.py 注册了 StubLLMProvider——返回确定
    性 JSON 清单与 Markdown 报告，不联网、不耗 token。所有走 LLM 的路径
    （coaching 重算 / 报告生成 / extract）都不再因 LLM_NOT_CONFIGURED 报错。

    session 第一个用例前切到 stub，session 结束（yield 末尾）自动还原原 llm.type——
    不依赖兄弟 fixture _restore_real_db 的间接兜底；后者对非 sqlite 库 / 进程被
    signal 杀掉 / 异常终止时不会跑还原。把还原放在本 fixture 自己的 yield 后是
    双保险：CI runner 复用同一个后端进程跑后续真实 LLM 用例时不会被桩污染。
    """
    import asyncio
    import httpx

    async def _login_token() -> str | None:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.post("/api/v1/auth/login",
                             json={"username": USERNAME, "password": PASSWORD})
            if r.status_code != 200:
                return None
            return r.json().get("access_token")

    async def _current_type(token: str) -> str:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/v1/admin/config/llm",
                            headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return str(r.json().get("type", "openai"))

    async def _put_type(token: str, value: str) -> int:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.put("/api/v1/admin/config/llm",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"type": value})
            return r.status_code

    try:
        token = asyncio.run(_login_token())
        if token is None:
            print(f"[e2e conftest] 激活 stub LLM 失败：登录 {BASE_URL} 失败，继续")
            yield
            return
        orig_type = asyncio.run(_current_type(token))
        code = asyncio.run(_put_type(token, "stub"))
        if code != 200:
            raise RuntimeError(f"激活 stub LLM 失败（llm.type=stub）：HTTP {code}")
    except Exception as e:  # noqa: BLE001
        # 后端离线或 stub provider 未注册——让 probe 阶段整体 skip，不破坏测试
        print(f"[e2e conftest] 激活 stub LLM 失败，继续：{e}")
        yield
        return

    yield

    try:
        code = asyncio.run(_put_type(token, orig_type))
        if code != 200:
            print(f"[e2e conftest] 还原 llm.type={orig_type} 失败：HTTP {code}；请手动恢复")
    except Exception as e:  # noqa: BLE001
        print(f"[e2e conftest] 还原 llm.type={orig_type} 失败，请手动恢复：{e}")


@pytest.fixture(scope="session")
def logdir(tmp_path_factory) -> object:
    """本次运行的全量帧流水目录（事后排查用，目录被 git 忽略）。"""
    return tmp_path_factory.mktemp(f"e2e_{time.strftime('%H%M%S')}")


@pytest.fixture
def make_client(api, logdir):
    """ChaosClient 工厂：make_client("名字", sid, client_id=...)。"""
    import chaos

    def _make(name: str, sid: str, client_id: str | None = None) -> chaos.ChaosClient:
        return chaos.ChaosClient(name, api.token or "", sid,
                                 base_url=BASE_URL, client_id=client_id, logdir=logdir)
    return _make


@pytest.fixture
def new_sid(api):
    """建一个访谈会话，返回 sid。"""
    async def _create(title: str, goal: str) -> str:
        await api._auth_headers()  # 预热 token，避免工厂拿到空 token
        return await api.create_interview(title, goal)
    return _create


@pytest.fixture(scope="session")
def backend_pid() -> int:
    """本机后端进程 PID；未提供则跳过依赖它的用例。"""
    if not BACKEND_PID or not BACKEND_PID.isdigit():
        pytest.skip("未设置 E2E_BACKEND_PID（本机后端进程号），跳过内存/残留连接检查")
    return int(BACKEND_PID)


def pytest_addoption(parser: pytest.Parser) -> None:
    """RSS 阈值参数化：默认 30MB/轮（只拦灾难级泄漏，小额由残留连接兜底）。"""
    parser.addoption(
        "--rss-budget-kb",
        action="store",
        type=int,
        default=30 * 1024,
        help="单轮会话允许的最大 RSS 增长（KB），默认 30720（30MB）。",
    )


@pytest.fixture(scope="session")
def rss_budget_kb(request: pytest.FixtureRequest) -> int:
    """RSS 增长预算（KB）。由 --rss-budget-kb 注入，默认 30MB。
    30MB 依据：Python 内存池不会把内存全还给 OS，RSS 小额抬升属正常的；仅每轮几十 MB
    量级才视为灾难级泄漏；并发量大的环境下可放宽到 --rss-budget-kb=102400（100MB）。
    """
    return request.config.getoption("--rss-budget-kb")


class _ConfigRestore:
    """临时改一项配置 + 退出时还原。返回的实例是个 async context manager。

    支持同一组下同时暂存、退出时一次性还原多项：如造「已 suspended 但 runtime
    仍寄存」的窗口需 grace=15 / liveness=60 同时调整。
    """

    def __init__(self, api, group: str, items: dict[str, str]):
        self.api = api
        self.group = group
        self.items = items
        self.original: dict[str, str] = {}

    async def __aenter__(self):
        cur = await _call_get(self.api, self.group)
        for k, target in self.items.items():
            self.original[k] = cur[k]
            code, _ = await self.api.put_config(self.group, {k: target})
            assert code == 200, f"临时设置 {self.group}.{k}={target} 失败"
        return self

    async def __aexit__(self, exc_type, exc, tb):
        for k, orig in self.original.items():
            code, _ = await self.api.put_config(self.group, {k: orig})
            assert code == 200, f"还原 {self.group}.{k}={orig} 失败"


@pytest.fixture
def restore_max_concurrent(api):
    """临时改 session.max_concurrent 后退出还原（先读原值、finally 还原原值）。
    避免硬编码回填 `10` 时若默认值不是 10、或进程被杀跳过 finally → 留下污染环境。

    用法：
        async with restore_max_concurrent("1"):
            ...
    """
    def _factory(target: str):
        return _ConfigRestore(api, "session", {"max_concurrent": target})
    return _factory


@pytest.fixture
def restore_runtime_windows(api):
    """同时暂存 / 还原 grace_period_s 与 liveness_window_s。僵尸用例要用
    grace=15 / liveness=60：缩短 grace 到 15s 让"断开→suspended"快速稳定，
    再让 liveness=60s 留下"runtime 仍寄存"的稳定窗口，全程 ≈95s 即走完。
    """
    def _factory(grace_s: str, liveness_s: str):
        return _ConfigRestore(api, "session", {
            "grace_period_s": grace_s,
            "liveness_window_s": liveness_s,
        })
    return _factory


@pytest.fixture
def restore_idle_window(api):
    """临时把 idle_timeout_s / idle_check_interval_s 缩到测试能等的秒数。

    生产 idle_timeout 默认 1800s（30 分钟），本用例在 CI 必须在秒级内完成，
    因此临时改为 idle=10s / check=3s，让"在线无活动"在秒级触发
    session.suspended；exit finally 一律还原。
    """
    def _factory(idle_s: str, check_s: str):
        return _ConfigRestore(api, "session", {
            "idle_timeout_s": idle_s,
            "idle_check_interval_s": check_s,
        })
    return _factory


async def _call_get(api, group: str) -> dict:
    """GET /admin/config/{group}：读当前配置原值（string），与 str 输入相容。"""
    async with await api._client() as c:
        r = await c.get(f"/api/v1/admin/config/{group}", headers=await api._auth_headers())
        r.raise_for_status()
        return r.json()


def rss_kb(pid: int) -> int:
    """后端进程常驻内存（KB）。"""
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                         capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


def count_asr_connections(pid: int) -> int:
    """后端到 FunASR 的 ESTABLISHED 连接数（会话全结束后应为 0——连接泄漏回归检查）。

    lsof 多条件默认做"并集"而非"交集"，必须显式补 `-a`（AND）才能同时匹配
    "进程 + 目标地址 + 状态" 三条约束；缺 `-a` 会把「本进程的全部 TCP 连接
    与到 ASR_ADDR 的全部 TCP 连接」并起来，结果里目标不是 ASR_ADDR 的本地
    连接也会被算进去——这条计数会膨胀、且需要后续 `in line` 筛回，不稳。

    输出列顺序固定：`COMMAND  PID  USER  FD  TYPE  DEVICE  SIZE/OFF  NODE  NAME`。
    必须读 parts[1]（PID）——parts[0] 是 COMMAND 列（BSD/macOS 上还可能是二进制
    路径片段），不能用其值匹配目标进程 PID。
    """
    if shutil.which("lsof") is None:
        pytest.skip("本机无 lsof，无法检查残留连接")
    # lsof 无匹配行时退出码为 1，属正常（check=False）
    out = subprocess.run(
        ["lsof", "-nP", "-a",
         "-p", str(pid),
         "-iTCP@" + ASR_ADDR,
         "-sTCP:ESTABLISHED"],
        capture_output=True, text=True, check=False,
    )
    n = 0
    for line in out.stdout.splitlines():
        parts = line.split()
        # 标题行首列是 "COMMAND"，不参与计数；按列对位（PID 在 parts[1]）
        if len(parts) >= 2 and parts[1] == str(pid):
            n += 1
    return n


# --- Playwright admin 辅助（8001，frontend webServer 起的 uvicorn）---------
@pytest.fixture(scope="session")
def base_url() -> str:
    """Playwright 端后台 base URL（默认 8001，与 webServer 对齐）。"""
    return PLAYWRIGHT_BASE_URL


@pytest.fixture(scope="session")
def admin_username() -> str:
    return "admin"


@pytest.fixture(scope="session")
def admin_password() -> str:
    return _TEST_ADMIN_PASSWORD


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    r.raise_for_status()
    body = r.json()
    # 后端 token 字段可能是 token / access_token，按既有接口优先 token
    return body.get("token") or body["access_token"]


@pytest.fixture(scope="session")
async def admin_token(base_url: str, admin_username: str, admin_password: str) -> str:
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        return await _login(client, admin_username, admin_password)


@pytest.fixture
def admin_headers(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}

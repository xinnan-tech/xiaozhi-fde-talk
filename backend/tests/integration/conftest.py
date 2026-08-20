"""集成测试公共 fixture：HTTP 客户端 / 登录 / 建会话 / WebM 编码。

服务未运行时整体跳过（pytest_collection_modifyitems 钩子）。
对应 design §10 PR2：集成测试 DB 隔离 + 演示账号 + 模型可用性探测。

登录账号默认从环境变量读，避免把生产密码改弱来迁就测试：
- APP_ADMIN_USERNAME（默认 admin）
- APP_ADMIN_PASSWORD（默认 admin）
要让这套测试在跑着真实强密码的服务上通过，跑测试时显式 export
APP_ADMIN_PASSWORD='<服务实际密码>'（用户名仍是 admin）。
"""
from __future__ import annotations

import io as _io
import os
import uuid

import httpx
import pytest

BASE_URL = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"

# admin 默认账号：env 覆盖，缺省维持原行为（admin/admin）
ADMIN_USERNAME = os.environ.get("APP_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("APP_ADMIN_PASSWORD", "admin")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """服务离线时跳过全部集成测试，避免误报。"""
    import asyncio

    async def _probe() -> bool:
        try:
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=5) as client:
                r = await client.get("/health")
                return r.status_code == 200
        except Exception:
            return False

    online = asyncio.run(_probe())
    if online:
        return
    reason = "后端服务未运行（http://localhost:8000/health 不可达），跳过集成测试；起服务后再跑：另开终端 `python main.py`"
    for item in items:
        # 仅跳过带 integration marker 的用例（pytest_collection_modifyitems 接收全量 items）
        if item.get_closest_marker("integration"):
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
        yield c


# 同一 (username, password) 的 token 整个测试进程内复用：每个用例都重新登录
# 会撞上登录限流（同 ip:username 令牌桶容量 5），限流本身是被测特性。
_login_token_cache: dict[tuple[str, str], str] = {}


@pytest.fixture
def login():
    """登录返回 token。默认账号读 APP_ADMIN_USERNAME/APP_ADMIN_PASSWORD env，
    缺省 admin/admin（保留旧行为）。显式传 username/password 时覆盖 env。
    """
    async def _login(
        client: httpx.AsyncClient,
        username: str = ADMIN_USERNAME,
        password: str = ADMIN_PASSWORD,
    ) -> str:
        key = (username, password)
        if key not in _login_token_cache:
            r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
            assert r.status_code == 200, f"login {username} failed: {r.text}"
            _login_token_cache[key] = r.json()["access_token"]
        return _login_token_cache[key]
    return _login


@pytest.fixture
def create_user():
    """动态创建一个用户（直接 DB 插入），用于资源隔离等需要第二个用户的场景。"""
    from app.core.security import hash_password
    from app.persistence.db import SessionLocal
    from app.persistence.models import User

    async def _create(username: str, password: str) -> str:
        from sqlalchemy import select

        async with SessionLocal() as session:
            existing = await session.execute(
                select(User).where(User.username == username)
            )
            if existing.scalar_one_or_none() is None:
                session.add(User(
                    id=str(uuid.uuid4()),
                    username=username,
                    password_hash=hash_password(password),
                ))
                await session.commit()
        return username
    return _create


@pytest.fixture
def create_session():
    async def _create(
        client: httpx.AsyncClient,
        token: str,
        template_id: str = "pm-research",
    ) -> str:
        r = await client.post(
            "/api/v1/interviews",
            json={"template_id": template_id, "base_info": {"project": "App X"}, "goal": "g"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, f"create failed: {r.text}"
        return r.json()["id"]
    return _create


@pytest.fixture
def end_session():
    """结束访谈（REST，会话状态控制的唯一入口；WS 不承载 end）。"""
    async def _end(client: httpx.AsyncClient, token: str, session_id: str) -> None:
        r = await client.post(
            f"/api/v1/interviews/{session_id}/end",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, f"end failed: {r.text}"
    return _end


@pytest.fixture
def zh_webm() -> bytes:
    """生成内嵌测试音频：静音 + 正弦波 → WebM/Opus（模拟浏览器 MediaRecorder 上行）。"""
    import av
    import numpy as np

    # 生成 1 秒测试音频：500ms 静音 + 500ms 正弦波（模拟语音）
    sample_rate = 16000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), dtype=np.float32)
    # 500ms 静音 + 500ms 1000Hz 正弦波
    silence = np.zeros(sample_rate // 2, dtype=np.int16)
    tone = (np.sin(2 * np.pi * 1000 * t[sample_rate // 2:]) * 8000).astype(np.int16)
    pcm = np.concatenate([silence, tone])

    out = _io.BytesIO()
    cont = av.open(out, mode="w", format="webm")
    stream = cont.add_stream("libopus", rate=sample_rate)
    stream.layout = "mono"
    fsz = 320
    a = pcm.copy()
    if len(a) % fsz:
        a = np.pad(a, (0, fsz - len(a) % fsz))
    for i in range(0, len(a), fsz):
        fr = av.AudioFrame.from_ndarray(a[i:i + fsz].reshape(1, -1), format="s16", layout="mono")
        fr.sample_rate = sample_rate
        for p in stream.encode(fr):
            cont.mux(p)
    for p in stream.encode(None):
        cont.mux(p)
    cont.close()
    return out.getvalue()

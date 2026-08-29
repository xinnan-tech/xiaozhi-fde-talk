"""顶层 pytest 配置。

- 注册 markers：integration（依赖运行中的服务）、contracts（端口契约）
- 提供 service_online 探测（集成测试在服务未运行时整体跳过）
- _restore_real_db：整轮测试前后快照/恢复真实库（防测试污染线上配置/用户）
对应 design §10 PR2：测试拆分 + conftest 分层。
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest  # F401 (re-exported for tests)

BASE_URL = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"

# E2E 子套件 admin fixture 共享的默认密码。跟 tests/integration/conftest.py
# 的 ADMIN_PASSWORD（"admin"）保持一致；该常量先前在 e2e/conftest.py
# `from tests.conftest import _TEST_ADMIN_PASSWORD` 引用，但顶层没定义过，
# 是历史遗漏——加回去让 e2e admin fixture 不再破导入。
_TEST_ADMIN_PASSWORD = "admin"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: 依赖运行中的后端服务（起 `python main.py` 后再跑）")
    config.addinivalue_line("markers", "contracts: 外部端口契约测试（依赖模型/网络）")


@pytest.fixture(scope="session")
def service_online() -> bool:
    """探测后端服务是否在线；离线时集成测试整体跳过。"""
    async def _probe() -> bool:
        try:
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=5) as client:
                r = await client.get("/health")
                return r.status_code == 200
        except Exception:
            return False

    return asyncio.run(_probe())


@pytest.fixture(scope="session", autouse=True)
def _restore_real_db():
    """测试防污染网：整轮 pytest 前后对真实库做表级快照/恢复。

    部分测试连真实库（集成测试打运行中的 :8000），会覆盖 system_config、新建/改
    临时用户。不恢复就污染线上——曾经就有集成测试把 LLM 配置盖成测试值
    （base_url=https://dashscope.aliyuncs.com/compatible-mode/v1、api_key=new-secret）
    导致所有 LLM 调用失败。
    这里整轮前后快照 system_config + users，跑后精确还原：只动被测试改动的行（未改零
    写入）；真实库不可用（未初始化 / CI 无库 / 非 sqlite 文件库）时静默跳过。

    恢复范围：被「覆盖」或影响登录/安全的表——system_config（逐 key 还原 + 删测试新增
    key）、users（删测试新建用户 + 还原被改的 password_hash/role）。访谈记录属测试
    「新增」、非覆盖、不影响功能，不在范围内。
    注：恢复只写 DB；运行中后端进程的 ConfigStore 缓存不会被清——集成测试后建议重启后端。
    """
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.settings import get_settings
    from app.persistence.models import SystemConfig, User

    url = get_settings().db_url
    # 只对存在的 sqlite 文件库做快照：避免在无库环境凭空创建 DB 文件、也不碰非 sqlite 库
    if not url.startswith("sqlite"):
        yield
        return
    db_path = url.split("///", 1)[-1]
    if db_path == ":memory:" or not os.path.exists(db_path):
        yield
        return

    def _engine():
        # timeout：后端运行时可能持写锁，让 sqlite 等锁而非立刻 SQLITE_BUSY
        return create_async_engine(url, connect_args={"timeout": 30.0})

    async def _snapshot():
        engine = _engine()
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as s:
                cfg = {r.key: r.value for r in (await s.execute(select(SystemConfig))).scalars().all()}
                users = {u.username: (u.password_hash, u.role) for u in (await s.execute(select(User))).scalars().all()}
            return cfg, users
        finally:
            await engine.dispose()

    try:
        snap = asyncio.run(_snapshot())
    except Exception:  # noqa: BLE001
        snap = None  # 表缺失等 → 不做恢复

    yield

    if snap is None:
        return
    cfg0, users0 = snap

    async def _restore():
        engine = _engine()
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as s:
                # system_config：删测试新增 key，还原/重插原有 key
                if cfg0:
                    await s.execute(delete(SystemConfig).where(SystemConfig.key.not_in(list(cfg0.keys()))))
                for k, v in cfg0.items():
                    row = await s.get(SystemConfig, k)
                    if row is None:
                        s.add(SystemConfig(key=k, value=v))
                    elif row.value != v:
                        row.value = v
                # users：删测试新建用户，还原被改的密码/角色（cfg0/users0 非空才删，绝不全删）
                if users0:
                    await s.execute(delete(User).where(User.username.not_in(list(users0.keys()))))
                    for uname, (ph, role) in users0.items():
                        row = (await s.execute(select(User).where(User.username == uname))).scalars().first()
                        if row is None:
                            continue
                        if row.password_hash != ph:
                            row.password_hash = ph
                        if row.role != role:
                            row.role = role
                await s.commit()
        finally:
            await engine.dispose()

    try:
        asyncio.run(_restore())
    except Exception as e:  # noqa: BLE001
        print(f"[conftest] 测试后恢复真实库失败，请手动检查 system_config/users：{e}")


# ---- i18n locale fixtures (T06) ----
# 给测试一个明确的 locale 上下文；fixture 内自带 teardown，避免污染后续用例。
from app.core.i18n.context import force_locale, reset_locale  # noqa: E402


@pytest.fixture
def force_locale_ctx():
    """Returns a function; yields a getter for current locale."""
    return force_locale


@pytest.fixture
def en_locale(force_locale_ctx):
    tok = force_locale_ctx("en-US")
    try:
        yield "en-US"
    finally:
        reset_locale(tok)


@pytest.fixture
def zh_cn_locale(force_locale_ctx):
    tok = force_locale_ctx("zh-CN")
    try:
        yield "zh-CN"
    finally:
        reset_locale(tok)


@pytest.fixture
def zh_tw_locale(force_locale_ctx):
    tok = force_locale_ctx("zh-TW")
    try:
        yield "zh-TW"
    finally:
        reset_locale(tok)

"""bootstrap.init_db prod 强制走 Alembic 迁移。

回归需求（Wave 3 P1）：
- env=prod + APP_DB_USE_ALEMBIC 未设 → 必须进 alembic 分支
- env=prod + APP_DB_USE_ALEMBIC=0 显式覆盖 → 仍走 alembic（prod 强制），
  防止运维忘记翻 env 又想通过「关 alembic」绕过迁移历史
- env=dev → 走 Base.metadata.create_all + 自愈路径（不调 alembic）
- env=prod + alembic 失败 → 抛 RuntimeError，lifespan 把它转 os._exit
"""
from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """清 APP_ENV / APP_DB_USE_ALEMBIC，再让各用例按需 set。"""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("APP_DB_USE_ALEMBIC", raising=False)
    yield


@pytest.mark.asyncio
async def test_prod_env_runs_alembic(monkeypatch):
    """env=prod → 必须调 subprocess.run(alembic upgrade head)。"""
    monkeypatch.setenv("APP_ENV", "prod")

    called: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        called["cmd"] = cmd
        called["kwargs"] = kwargs
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        return r

    # 阻断副作用：Base.metadata.create_all + 自愈。
    # engine.begin 是属性不能直接 setattr，patch 调用的源头（Base.metadata.create_all）。
    create_all_calls: list[object] = []

    from sqlalchemy.ext.asyncio import AsyncEngine

    class _FakeCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def run_sync(self, fn):
            create_all_calls.append(fn)
            return None

        async def execute(self, *args, **kwargs):
            return None

    def fake_begin(self):
        return _FakeCtx()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(AsyncEngine, "begin", fake_begin)

    from app.persistence.bootstrap import init_db
    await init_db()

    assert called["cmd"] == ["alembic", "upgrade", "head"], \
        f"prod 模式必须走 alembic，实际跑了 {called['cmd']}"
    assert create_all_calls == [], "prod 不应走 create_all"


@pytest.mark.asyncio
async def test_prod_env_overrides_disable_alembic(monkeypatch):
    """env=prod 即便显式 APP_DB_USE_ALEMBIC=0 也走 alembic（强制）。"""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("APP_DB_USE_ALEMBIC", "0")

    called: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        called["cmd"] = cmd
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        return r

    from sqlalchemy.ext.asyncio import AsyncEngine

    class _FakeCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def run_sync(self, fn):
            called["create_all"] = True

        async def execute(self, *args, **kwargs):
            return None

    def fake_begin(self):
        return _FakeCtx()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(AsyncEngine, "begin", fake_begin)

    from app.persistence.bootstrap import init_db
    await init_db()

    assert called["cmd"] == ["alembic", "upgrade", "head"], \
        "prod 强制 alembic，不允许用 APP_DB_USE_ALEMBIC=0 绕过"


@pytest.mark.asyncio
async def test_dev_env_skips_alembic(monkeypatch):
    """env=dev 默认走 create_all，不调 alembic。"""
    monkeypatch.setenv("APP_ENV", "dev")

    subprocess_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        subprocess_calls.append(cmd)
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        return r

    from sqlalchemy.ext.asyncio import AsyncEngine

    class _FakeCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def run_sync(self, fn):
            pass

        async def execute(self, *args, **kwargs):
            return None

    def fake_begin(self):
        return _FakeCtx()

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(AsyncEngine, "begin", fake_begin)

    async def _noop_async(*_a, **_k):
        return None

    monkeypatch.setattr("app.persistence.bootstrap._ensure_columns", _noop_async)

    from app.persistence.bootstrap import init_db
    await init_db()

    assert subprocess_calls == [], \
        f"dev 不应调 alembic，实际 {subprocess_calls}"


@pytest.mark.asyncio
async def test_prod_alembic_failure_raises(monkeypatch):
    """env=prod + alembic 退出码非 0 → init_db 抛 RuntimeError（含 stdout+stderr）。"""
    monkeypatch.setenv("APP_ENV", "prod")

    def fake_run(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 1
        r.stdout = "alembic_stdout"
        r.stderr = "alembic_stderr"
        return r

    monkeypatch.setattr("subprocess.run", fake_run)

    from app.persistence.bootstrap import init_db
    with pytest.raises(RuntimeError) as ei:
        await init_db()
    msg = str(ei.value)
    assert "alembic_stderr" in msg
    assert "alembic_stdout" in msg

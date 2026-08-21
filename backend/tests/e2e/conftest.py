"""E2E 测试辅助：仅备 token helper / 工具 fixtures。

不接管进程生命周期：uvicorn 由 Playwright `webServer` 统一拉起。
本模块给手动 `pytest backend/tests/e2e/` 调用时复用。
"""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

import httpx
import pytest

# 复用的既有常量（不重新定义，避免与既有 conftest 漂移）
from tests.conftest import _TEST_ADMIN_PASSWORD

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8001")


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


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

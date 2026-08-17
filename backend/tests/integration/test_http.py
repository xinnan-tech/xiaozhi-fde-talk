"""集成测试：HTTP 健康检查 + 访谈 CRUD + 资源隔离。

依赖运行中的后端服务（pytest_collection_modifyitems 在服务离线时整体跳过）。
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_health(client):
    r = await client.get("/health")
    body = r.json()
    assert r.status_code == 200 and body.get("status") == "ok" and "version" in body, f"health failed: {r.text}"


async def test_interviews(client, login, create_session, create_user):
    admin_token = await login(client, "admin", "admin")
    await create_user("bob", "bob")
    bob_token = await login(client, "bob", "bob")
    admin_h = {"Authorization": f"Bearer {admin_token}"}
    bob_h = {"Authorization": f"Bearer {bob_token}"}

    sid = await create_session(client, admin_token)
    assert sid

    r = await client.get(f"/api/v1/interviews/{sid}", headers=admin_h)
    assert len(r.json()["items"]) == 6 and all(it["status"] == "todo" for it in r.json()["items"])

    r = await client.get(f"/api/v1/interviews/{sid}", headers=bob_h)
    assert r.status_code == 404, f"隔离失败: {r.status_code}"

    assert len((await client.get("/api/v1/interviews", headers=bob_h)).json()["items"]) == 0

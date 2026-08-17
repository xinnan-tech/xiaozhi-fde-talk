"""集成测试：鉴权 + 模板 + Skill API。

依赖运行中的后端服务（pytest_collection_modifyitems 在服务离线时整体跳过）。
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_auth_and_templates(client, login):
    r = await client.get("/api/v1/templates")
    assert r.status_code == 401, f"expected 401, got {r.status_code}"

    token = await login(client)

    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401

    r = await client.get("/api/v1/templates", headers={"Authorization": f"Bearer {token}"})
    items = r.json()["items"]
    assert any(i["id"] == "pm-research" for i in items), items

    r = await client.get("/api/v1/templates/pm-research", headers={"Authorization": f"Bearer {token}"})
    must_ids = [m["id"] for m in r.json()["coaching"]["must_ask"]]
    assert must_ids == ["objective", "pain", "current_solution", "constraints", "decision", "success"], must_ids


async def test_skills_api(client, login):
    token = await login(client)
    h = {"Authorization": f"Bearer {token}"}
    r = await client.get("/api/v1/skills", headers=h)
    assert r.status_code == 200, r.text
    ids = [s["id"] for s in r.json()["items"]]
    assert "echo" in ids, ids

    r = await client.post(
        "/api/v1/internal/skills/echo/invoke",
        headers=h,
        json={"inputs": {"title": "API", "content": "ok"}},
    )
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert "ok" in r.json()["artifact"]["content"]

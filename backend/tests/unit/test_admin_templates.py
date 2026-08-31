"""admin 模板 CRUD 端点：权限、校验、版本自增、删除保护。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.persistence.db import SessionLocal
from app.persistence.models import InterviewRecord, User
from app.services.auth.token import create_access_token


@pytest.fixture(scope="module")
async def _lifespan_app():
    import os
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    os.environ.setdefault("APP_ENV", "dev")
    from app.app import create_app
    from app.core.settings import get_settings
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


async def _admin_headers() -> dict[str, str]:
    """建临时 admin（password_changed_at 有值）+ 直接签 token（pwd_ver 对齐）。"""
    suffix = uuid.uuid4().hex[:8]
    uid = f"tpl-admin-{suffix}"
    ts = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        db.add(User(
            id=uid, username=f"tpl_admin_{suffix}",
            password_hash="x", role="admin", password_changed_at=ts,
        ))
        await db.commit()
    token = await create_access_token(
        subject=uid, pwd_ver=int(ts.timestamp()), extra={"role": "admin"},
    )
    return {"Authorization": f"Bearer {token}"}


def _body(tid: str) -> dict:
    return {
        "id": tid, "version": "1", "icon_url": "", "icon_alt": "🧪",
        "name": "接口测试模板",
        "session": {
            "name": "s", "goal": "", "base_fields": [
                {"key": "project", "label": "项目"},
            ],
            "setup": {"intro": "", "extract_to": ["project"], "required": []},
        },
        "coaching": {"playbook": "", "must_ask": [{"id": "q1", "text": "问"}]},
        "report": {"doc": ""},
        "safety": [],
    }


@pytest.mark.asyncio
async def test_requires_admin(_lifespan_app):
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/api/v1/admin/templates")).status_code == 401


@pytest.mark.asyncio
async def test_crud_flow(_lifespan_app):
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _admin_headers()
        # 用 uuid 隔离——同一 sqlite 文件跨测试可能残留同 id
        tid = f"route-{uuid.uuid4().hex[:8]}"

        # 列表含种子 pm-research
        r = await c.get("/api/v1/admin/templates", headers=h)
        assert r.status_code == 200
        assert any(i["id"] == "pm-research" for i in r.json())
        assert {"id", "name", "icon_url", "icon_alt", "version",
                "updated_at", "referenced"} == set(r.json()[0].keys())

        # 新建
        r = await c.post("/api/v1/admin/templates", json=_body(tid), headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["id"] == tid

        # 重复 id → 409 + code
        r = await c.post("/api/v1/admin/templates", json=_body(tid), headers=h)
        assert r.status_code == 409
        assert r.json()["code"] == "template.id_taken"

        # 更新：客户端必须带着上次响应的 version（乐观锁），
        # 服务端 +1 后写回。先从列表拿到当前 version（=1），再 PUT 时带上
        listed = (await c.get("/api/v1/admin/templates", headers=h)).json()
        current = next(i for i in listed if i["id"] == tid)
        body = _body(tid)
        body["name"] = "改名"
        body["version"] = current["version"]  # 客户端手里是「上次响应」里的 version
        r = await c.put(f"/api/v1/admin/templates/{tid}", json=body, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["version"] == "2"
        assert r.json()["name"] == "改名"

        # 旧 version 再 PUT → 409 冲突（#1：之前是恒真更新静默吞对方改动）
        stale = _body(tid)
        stale["version"] = "1"  # 已经过期的版本
        stale["name"] = "过期改名"
        r = await c.put(f"/api/v1/admin/templates/{tid}", json=stale, headers=h)
        assert r.status_code == 409
        assert r.json()["code"] == "template.version_conflict"

        # 路径与 body id 不一致 → 422
        r = await c.put(
            f"/api/v1/admin/templates/{tid}",
            json=_body("other-id"), headers=h,
        )
        assert r.status_code == 422

        # 业务校验（字段 key 重复）→ 422 + code
        bad = _body(tid)
        bad["session"]["base_fields"].append({"key": "project", "label": "重复"})
        r = await c.put(f"/api/v1/admin/templates/{tid}", json=bad, headers=h)
        assert r.status_code == 422
        assert r.json()["code"] == "template.invalid.duplicate_field"

        # 无引用可删
        r = await c.delete(f"/api/v1/admin/templates/{tid}", headers=h)
        assert r.status_code == 200 and r.json()["ok"] is True


@pytest.mark.asyncio
async def test_delete_referenced_409(_lifespan_app):
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _admin_headers()
        # 用 uuid 隔离——同 sqlite 文件跨测试可能残留同 id
        tid = f"route-{uuid.uuid4().hex[:8]}"
        iid = f"{tid}-i1"
        await c.post("/api/v1/admin/templates", json=_body(tid), headers=h)
        async with SessionLocal() as db:
            db.add(InterviewRecord(
                id=iid, template_id=tid, status="created",
            ))
            await db.commit()
        try:
            r = await c.delete(f"/api/v1/admin/templates/{tid}", headers=h)
            assert r.status_code == 409
            assert r.json()["code"] == "template.referenced"
        finally:
            async with SessionLocal() as db:
                rec = await db.get(InterviewRecord, iid)
                await db.delete(rec)
                await db.commit()
            await c.delete(f"/api/v1/admin/templates/{tid}", headers=h)


@pytest.mark.asyncio
async def test_user_facing_templates_still_work(_lifespan_app):
    """现有 GET /api/v1/templates 数据源切到 DB 后行为不变（登录用户可读）。"""
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _admin_headers()
        r = await c.get("/api/v1/templates", headers=h)
        assert r.status_code == 200
        assert any(i["id"] == "pm-research" for i in r.json()["items"])

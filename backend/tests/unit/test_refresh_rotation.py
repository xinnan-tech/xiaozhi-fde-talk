"""/auth/refresh rotation 语义回归（refresh_sessions 表落库后）。

覆盖：
- refresh 成功 → 旧 refresh cookie 被新 token 轮换（Set-Cookie + body），
  旧 jti 行置 rotated，新 jti 行登记 active
- grace 窗内旧 token 立即重放 → 200（多 tab 并发刷新容错），且不影响
  其他在用 token
- grace 窗外旧 token 重放（人为把 rotated_at 拨回 120s）→ 401 +
  该用户全部 refresh session 被击杀（reuse 检测 → 全家撤销）
- logout 撤销落 DB（无行 legacy token 补登记 revoked 行）
- 无行 token（模拟迁移前签发的 legacy token）→ 按有效处理并首见补登记
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from app.core.config_store import get_config_store
from app.persistence.bootstrap import init_db
from app.persistence.db import SessionLocal, engine
from app.persistence.models import RefreshSessionRecord, User
from app.services.auth.token import decode_token
from app.core.settings import get_settings
from app.core.i18n.context import current_locale
from app.core.i18n.errors import I18nError


@asynccontextmanager
async def _stub_lifespan(_app):
    """同 test_token_refresh.py：init_db + config warm + JWT secret 注入。"""
    await init_db()
    await get_config_store().warm()
    from app.core.secret import JWTSecretResolver
    resolver = JWTSecretResolver(get_settings(), SessionLocal)
    get_settings().jwt_secret = await resolver.resolve()
    yield
    await engine.dispose()


def _wire_exception_handler(app: FastAPI) -> None:
    @app.exception_handler(I18nError)
    async def _i18n_handler(request, exc: I18nError):  # noqa: ARG001
        locale = current_locale()
        return JSONResponse(
            status_code=exc.http_status,
            content={"detail": exc.localized(locale=locale), "code": exc.code},
            headers={"Content-Language": locale},
        )


@pytest.fixture
async def _app():
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    get_settings.cache_clear()
    app = FastAPI(title="stub")
    app.router.lifespan_context = _stub_lifespan
    from app.transport.http.routes import router as api_router
    app.include_router(api_router)
    _wire_exception_handler(app)
    async with _stub_lifespan(app):
        yield app


@pytest.fixture
async def reset_state(_app):
    """每个用例清 users + refresh_sessions + allow_registration + 限流桶。"""
    from sqlalchemy import text
    from app.transport.http.routes.auth import _reset_for_test
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM users"))
        await s.execute(text("DELETE FROM refresh_sessions"))
        await s.execute(text("DELETE FROM system_config WHERE key = 'auth.allow_registration'"))
        await s.commit()
    get_config_store().invalidate()
    _reset_for_test()
    yield _app
    async with SessionLocal() as s:
        await s.execute(text("DELETE FROM users"))
        await s.execute(text("DELETE FROM refresh_sessions"))
        await s.execute(text("DELETE FROM system_config WHERE key = 'auth.allow_registration'"))
        await s.commit()
    get_config_store().invalidate()
    _reset_for_test()


async def _make_user(username: str = "alice") -> str:
    """建一个可登录用户，返回 user_id。"""
    from app.core.security import hash_password_async
    uid = str(uuid.uuid4())
    pwd_hash = await hash_password_async("StrongP@ssW0rd")
    async with SessionLocal() as s:
        s.add(User(
            id=uid, username=username,
            password_hash=pwd_hash, role="user",
            password_changed_at=datetime.now(timezone.utc),
        ))
        await s.commit()
    return uid


async def _expire_grace(jti: str) -> None:
    """把行 rotated_at 拨回 120s 前——模拟 grace 窗已过（不真 sleep 60s）。"""
    async with SessionLocal() as s:
        await s.execute(
            update(RefreshSessionRecord)
            .where(RefreshSessionRecord.jti == jti)
            .values(rotated_at=datetime.now(timezone.utc) - timedelta(seconds=120))
        )
        await s.commit()


async def _row(jti: str) -> RefreshSessionRecord | None:
    async with SessionLocal() as s:
        return await s.get(RefreshSessionRecord, jti)


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_registers_rows(reset_state):
    """refresh 成功：新 refresh cookie ≠ 旧值，body 带 refresh_token；
    旧 jti 行 status=rotated（rotated_at 已锚定），新 jti 行 status=active。"""
    app = reset_state
    await _make_user()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        assert r.status_code == 200
        rt1 = c.cookies.get("refresh-token")
        old_jti = decode_token(rt1)["jti"]

        r2 = await c.post("/api/v1/auth/refresh")
    assert r2.status_code == 200, r2.text
    rt2 = c.cookies.get("refresh-token")
    assert rt2 and rt2 != rt1, "refresh 后 refresh cookie 必须被新 token 轮换"
    body = r2.json()
    assert body["refresh_token"] == rt2, "body 必须携带新 refresh_token（兼容路径）"
    assert body["access_token"], "body 必须仍携带 access_token"

    old_row = await _row(old_jti)
    assert old_row is not None, "旧 jti 首见 rotation 必须补登记"
    assert old_row.status == "rotated"
    assert old_row.rotated_at is not None
    new_row = await _row(decode_token(rt2)["jti"])
    assert new_row is not None and new_row.status == "active"


@pytest.mark.asyncio
async def test_grace_window_allows_immediate_replay(reset_state):
    """多 tab 并发场景：refresh 后立刻用旧 token 再刷 → 200（grace 窗内），
    不误杀；新换出的 token 也仍可用。"""
    app = reset_state
    await _make_user()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        rt1 = c.cookies.get("refresh-token")

        # tab A 正常 refresh → 旧 jti rotated（进入 grace 窗）
        r_tab_a = await c.post("/api/v1/auth/refresh")
        assert r_tab_a.status_code == 200
        rt2 = c.cookies.get("refresh-token")

        # tab B 携带旧 token 的并发请求（grace 窗内到达）→ 放行
        c.cookies.set("refresh-token", rt1)
        r_tab_b = await c.post("/api/v1/auth/refresh")
        assert r_tab_b.status_code == 200, r_tab_b.text

        # grace 命中不刷新锚点：旧行 rotated_at 不因窗内重放而后移
        old_row = await _row(decode_token(rt1)["jti"])
        assert old_row.status == "rotated"

        # tab A 换出的新 token 依旧有效
        c.cookies.set("refresh-token", rt2)
        r_rt2 = await c.post("/api/v1/auth/refresh")
    assert r_rt2.status_code == 200, "grace 窗内重放不得击杀其他在用 token"


@pytest.mark.asyncio
async def test_reuse_outside_grace_kills_all_user_sessions(reset_state):
    """grace 窗外重放 = 泄露信号：401 + 该用户全部 refresh session 撤销
    （包括另一台「设备」的在用 token）。"""
    app = reset_state
    await _make_user()
    transport = ASGITransport(app=app)

    # 设备 A / 设备 B 各自登录（两个独立 cookie jar = 两个 session）
    async with AsyncClient(transport=transport, base_url="http://t") as dev_a:
        await dev_a.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        rt_a = dev_a.cookies.get("refresh-token")
        # 设备 A refresh → rt_a 置 rotated
        r = await dev_a.post("/api/v1/auth/refresh")
        assert r.status_code == 200
        rt_a2 = dev_a.cookies.get("refresh-token")

        async with AsyncClient(transport=transport, base_url="http://t") as dev_b:
            await dev_b.post("/api/v1/auth/login", json={
                "username": "alice", "password": "StrongP@ssW0rd",
            })
            rt_b = dev_b.cookies.get("refresh-token")

            # 攻击者重放设备 A 的旧 token，且 grace 窗已过
            await _expire_grace(decode_token(rt_a)["jti"])
            async with AsyncClient(transport=transport, base_url="http://t") as attacker:
                attacker.cookies.set("refresh-token", rt_a)
                r_replay = await attacker.post("/api/v1/auth/refresh")
            assert r_replay.status_code == 401
            assert r_replay.json().get("code") == "auth.refresh_revoked"

            # 全家击杀：设备 B 的在用 token、设备 A 换出的新 token 全部 401
            r_b = await dev_b.post("/api/v1/auth/refresh")
            assert r_b.status_code == 401, "reuse 击杀必须波及该用户全部 session"
            assert r_b.json().get("code") == "auth.refresh_revoked"

    # 直接验表：该用户所有行均 revoked
    old_jti = decode_token(rt_a)["jti"]
    for jti in (old_jti, decode_token(rt_a2)["jti"], decode_token(rt_b)["jti"]):
        row = await _row(jti)
        assert row is not None and row.status == "revoked", (
            f"jti={jti[:6]}… 应为 revoked，实际 {row.status if row else None}"
        )


@pytest.mark.asyncio
async def test_rotate_reread_bypasses_identity_map_after_concurrent_revoke(reset_state):
    """PG/MySQL 竞态回归：route 首读行（identity map 缓存 active）→ 并发 logout
    经另一连接直写 revoked 并提交 → rotate() 条件 UPDATE rowcount=0 → 重读若命中
    identity map 的 stale 'active'，strict 检查永远 fall-through → logout 被旁路
    换出新对。重读必须绕过 identity map（db.refresh 强制 SELECT）。"""
    from app.persistence.repositories.refresh_session import RefreshSessionRepository

    app = reset_state
    uid = await _make_user()
    jti = "race-" + uuid.uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(days=7)

    async with SessionLocal() as s_setup:
        s_setup.add(RefreshSessionRecord(
            jti=jti, user_id=uid, status="active", expires_at=expires,
        ))
        await s_setup.commit()

    repo = RefreshSessionRepository()
    async with SessionLocal() as s_route:
        # 模拟 route 首读：行进入本 session 的 identity map（status=active）
        row = await s_route.get(RefreshSessionRecord, jti)
        assert row is not None and row.status == "active"

        # 并发 logout：另一连接直写 revoked + commit（不经过 s_route 的缓存）
        async with SessionLocal() as s_logout:
            await s_logout.execute(
                update(RefreshSessionRecord)
                .where(RefreshSessionRecord.jti == jti)
                .values(status="revoked")
            )
            await s_logout.commit()

        # rotate()：条件 UPDATE 落空（DB 已 revoked）→ 重读必须看见 revoked 并拒绝
        with pytest.raises(ValueError, match="并发改写"):
            await repo.rotate(
                s_route, old_jti=jti, old_row=row, old_expires_at=expires,
                user_id=uid, new_jti="race-new-" + uuid.uuid4().hex,
                new_expires_at=expires,
            )

    row_after = await _row(jti)
    assert row_after is not None and row_after.status == "revoked", (
        "被并发撤销的行不得被 rotation 复活"
    )


@pytest.mark.asyncio
async def test_rotate_legacy_pk_conflict_raises_valueerror_not_500(reset_state):
    """legacy 同 jti 并发首见（PG/MySQL）：双 tab 同时补登记撞 PK → IntegrityError
    必须转 ValueError（route 401），不得 500。SQLite 写锁下不可达；测试构造
    「T1 已 commit 补登记 + T2 首读 None」的最小冲突场景（old_row=None 直传）。"""
    from app.persistence.repositories.refresh_session import RefreshSessionRepository

    app = reset_state
    uid = await _make_user()
    jti = "legacy-race-" + uuid.uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(days=7)

    # 并发 T1 已抢先 commit 补登记
    async with SessionLocal() as s_t1:
        s_t1.add(RefreshSessionRecord(
            jti=jti, user_id=uid, status="rotated",
            rotated_at=datetime.now(timezone.utc), expires_at=expires,
        ))
        await s_t1.commit()

    repo = RefreshSessionRepository()
    async with SessionLocal() as s_route:
        with pytest.raises(ValueError, match="并发补登记"):
            await repo.rotate(
                s_route, old_jti=jti, old_row=None, old_expires_at=expires,
                user_id=uid, new_jti="legacy-new-" + uuid.uuid4().hex,
                new_expires_at=expires,
            )

    # T1 的登记行未被 T2 的失败 INSERT 破坏
    row = await _row(jti)
    assert row is not None and row.status == "rotated"


@pytest.mark.asyncio
async def test_rotate_row_purged_concurrently_raises_valueerror_not_500(reset_state):
    """rowcount=0 后行被并发 purge 删除（双 tab + JWT leeway 末 30s：赢家的
    rotate 顺手清了本行过期行）→ db.refresh 撞 ObjectDeletedError → 必须转
    ValueError（route 401），不得 500。"""
    from app.persistence.repositories.refresh_session import RefreshSessionRepository

    app = reset_state
    uid = await _make_user()
    jti = "purge-race-" + uuid.uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(days=7)

    async with SessionLocal() as s_setup:
        s_setup.add(RefreshSessionRecord(
            jti=jti, user_id=uid, status="active", expires_at=expires,
        ))
        await s_setup.commit()

    repo = RefreshSessionRepository()
    async with SessionLocal() as s_route:
        # route 首读：行入 identity map（active）
        row = await s_route.get(RefreshSessionRecord, jti)
        assert row is not None and row.status == "active"

        # 并发赢家 rotate + purge：本行被删除（直接 DELETE 模拟 purge 结果）
        async with SessionLocal() as s_winner:
            await s_winner.execute(
                delete(RefreshSessionRecord).where(RefreshSessionRecord.jti == jti)
            )
            await s_winner.commit()

        with pytest.raises(ValueError, match="并发清除"):
            await repo.rotate(
                s_route, old_jti=jti, old_row=row, old_expires_at=expires,
                user_id=uid, new_jti="purge-new-" + uuid.uuid4().hex,
                new_expires_at=expires,
            )


@pytest.mark.asyncio
async def test_logout_revoke_db_failure_returns_503_and_keeps_cookies(reset_state, monkeypatch):
    """fail-closed：revoke 落库失败 → 503 且不清 cookie（客户端保留 token 可
    重试）；清 cookie 返 200 会让用户以为已登出而行仍 active。"""
    from app.persistence.repositories.refresh_session import refresh_session_repo

    app = reset_state
    await _make_user()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        rt1 = c.cookies.get("refresh-token")

        async def _boom(*a, **k):
            raise RuntimeError("db down")
        monkeypatch.setattr(refresh_session_repo, "revoke_by_jti", _boom)

        r = await c.post("/api/v1/auth/logout")
    assert r.status_code == 503
    assert r.json().get("code") == "auth.logout_revocation_failed"
    # cookie 未被服务端清除
    assert "set-cookie" not in r.headers or "refresh-token=" not in (
        r.headers.get("set-cookie") or ""
    )


@pytest.mark.asyncio
async def test_classify_grace_seconds_override(reset_state):
    """grace 窗宽走 B 类配置（auth.refresh_grace_seconds）：同一 rotated 行
    在默认 60s 下判 reuse，调宽到 3600s 后判 valid。"""
    from app.persistence.repositories.refresh_session import (
        classify_refresh_session, refresh_session_repo,
    )

    app = reset_state
    uid = await _make_user()
    jti = "grace-cfg-" + uuid.uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(days=7)

    async with SessionLocal() as s:
        s.add(RefreshSessionRecord(
            jti=jti, user_id=uid, status="rotated",
            rotated_at=datetime.now(timezone.utc) - timedelta(seconds=120),
            expires_at=expires,
        ))
        await s.commit()

    async with SessionLocal() as s:
        row = await refresh_session_repo.get(s, jti)
        assert classify_refresh_session(row) == "reuse"
        assert classify_refresh_session(row, grace_seconds=3600) == "valid"


@pytest.mark.asyncio
async def test_logout_of_legacy_token_registers_revoked_row(reset_state):
    """迁移前签发的 token（无行）logout：补登记 revoked 行，随后 refresh 401。
    验证升级部署后 logout 语义不因「无行」而回退。"""
    app = reset_state
    await _make_user()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        rt1 = c.cookies.get("refresh-token")
        jti = decode_token(rt1)["jti"]

        # 人为抹掉登记行 = 模拟迁移前签发的 legacy token
        async with SessionLocal() as s:
            await s.execute(
                delete(RefreshSessionRecord).where(RefreshSessionRecord.jti == jti)
            )
            await s.commit()

        r_logout = await c.post("/api/v1/auth/logout")
        assert r_logout.status_code == 200
        row = await _row(jti)
        assert row is not None and row.status == "revoked", (
            "legacy token logout 必须补登记 revoked 行"
        )

        c.cookies.set("refresh-token", rt1)
        r_refresh = await c.post("/api/v1/auth/refresh")
    assert r_refresh.status_code == 401
    assert r_refresh.json().get("code") == "auth.refresh_revoked"


@pytest.mark.asyncio
async def test_legacy_token_without_row_refreshes_and_registers(reset_state):
    """迁移前签发的 token（无行）refresh：按有效处理（不踢存量用户），
  且首见即补登记 rotated——后续重放立即受 grace/reuse 约束。"""
    app = reset_state
    await _make_user()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post("/api/v1/auth/login", json={
            "username": "alice", "password": "StrongP@ssW0rd",
        })
        rt1 = c.cookies.get("refresh-token")
        jti = decode_token(rt1)["jti"]

        async with SessionLocal() as s:
            await s.execute(
                delete(RefreshSessionRecord).where(RefreshSessionRecord.jti == jti)
            )
            await s.commit()

        r = await c.post("/api/v1/auth/refresh")
        assert r.status_code == 200, "无行 legacy token 应按有效处理"
        row = await _row(jti)
        assert row is not None and row.status == "rotated", (
            "legacy token 首见 rotation 必须补登记 rotated"
        )
        rt2 = c.cookies.get("refresh-token")
        assert rt2 and rt2 != rt1

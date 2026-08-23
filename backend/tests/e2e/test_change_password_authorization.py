"""E2E：POST /auth/change-password 越权矩阵。

覆盖 5 组场景：
A. 请求体注入 user_id / username 是否影响「实际改谁」
B. JWT 当前用户与请求体里的旧密码不一致（旧密码错）→ 401
C. 路径 / query 参数是否允许指向他人
D. token 缺失 / 篡改 / 过期 → 401
E. 横向隔离：bob 改密后旧 token 吊销；alice 的 token 不受影响

所有用例的断言核心：改密后**必须**查非调用方用户（alice / admin）的
`password_hash` 仍是旧值（`bcrypt.checkpw(plain, fresh_hash)` 验旧密码仍可用）。
这是「改了不该改的人」的兜底断言——比单纯判 200 / 401 更严格。

不依赖同事 conftest.py——`--noconftest` 跑（项目已有先例）。
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.config_store import get_config_store
from app.core.security import verify_password
from app.persistence.db import SessionLocal
from app.persistence.models import User


_STRONG_PWD = "Strong1!pwd"
_STRONG_PWD_NEW = "Strong1!new"
_STRONG_PWD_NEW2 = "Strong1!v2"


@pytest.fixture(scope="module")
async def _lifespan_app():
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    os.environ.setdefault("APP_ENV", "dev")
    from app.app import create_app
    from app.core.settings import get_settings
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


async def _wipe_db() -> None:
    async with SessionLocal() as s:
        async with s.begin():
            await s.execute(text("DELETE FROM reports"))
            await s.execute(text("DELETE FROM interviews"))
            await s.execute(text("DELETE FROM users"))
            await s.execute(
                text("DELETE FROM system_config WHERE key = 'auth.allow_registration'")
            )


@pytest.fixture
async def empty_db(_lifespan_app):
    await _wipe_db()
    get_config_store().invalidate()
    yield _lifespan_app
    await _wipe_db()
    get_config_store().invalidate()


async def _register(c: AsyncClient, username: str, password: str = _STRONG_PWD) -> dict:
    r = await c.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": password,
            "confirm_password": password,
        },
    )
    assert r.status_code == 200, f"register {username} failed: {r.text}"
    return r.json()


async def _fresh_user(username: str) -> User:
    """从 DB fresh 读 user 行——绕开 ORM 缓存和 JWT pwd_ver 缓存。"""
    async with SessionLocal() as s:
        row = (await s.execute(select(User).where(User.username == username))).scalar_one()
        s.expunge_all()
        return row


# ─────────────────────────────────────────────────────────────────────────────
# Group A：请求体注入 user_id / username 试图改他人
# ─────────────────────────────────────────────────────────────────────────────


async def test_A1_body_user_id_field_does_not_change_other_user(empty_db):
    """bob 调改密，请求体加 `"user_id": "<admin id>"`。
    不论端点返回 200 还是 422/400：必须确认 admin 的 password_hash **未变**。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        admin = await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]

        admin_id = admin["user"]["id"]
        admin_before = await _fresh_user("admin1")

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
                "user_id": admin_id,  # 注入他人 id
            },
        )
        # 端点对未知字段的处理可能 200（pydantic 默认 ignore）/ 422（若 forbid）。
        # 这里只关心副作用：admin 密码不该被改。

        admin_after = await _fresh_user("admin1")
        assert admin_after.password_hash == admin_before.password_hash, (
            "危险：admin 的 password_hash 被改动了！body 注入 user_id 已越权"
        )
        assert verify_password(_STRONG_PWD, admin_after.password_hash), (
            "admin 旧密码应仍可用，但 verify_password 失败"
        )
        # 行为兜底：bob 自己必须被改
        assert verify_password(_STRONG_PWD_NEW, (await _fresh_user("bobby")).password_hash), (
            "bob 自己应已被改密成功（A1 主体行为）"
        )


async def test_A2_body_username_field_does_not_change_other_user(empty_db):
    """bob 调改密，请求体加 `"username": "admin1"` 试图改 admin → admin 必须 unchanged。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]

        admin_before = await _fresh_user("admin1")

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
                "username": "admin1",  # 注入他人 username
            },
        )

        admin_after = await _fresh_user("admin1")
        assert admin_after.password_hash == admin_before.password_hash, (
            "危险：admin 的 password_hash 被改动了！body 注入 username 已越权"
        )
        assert verify_password(_STRONG_PWD, admin_after.password_hash)
        assert verify_password(_STRONG_PWD_NEW, (await _fresh_user("bobby")).password_hash), (
            "bob 自己应已被改密成功"
        )


async def test_A3_normal_self_change_without_extra_fields(empty_db):
    """alice 调改密，请求体正常（无 user_id / username）→ 200 + 自己被改。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        alice = await _register(c, "alice")
        alice_token = alice["access_token"]

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 200, f"alice 自助改密应 200，实际 {r.status_code}：{r.text}"
        assert verify_password(_STRONG_PWD_NEW, (await _fresh_user("alice")).password_hash)


# ─────────────────────────────────────────────────────────────────────────────
# Group B：JWT 当前用户与请求体旧密码不一致
# ─────────────────────────────────────────────────────────────────────────────


async def test_B1_bob_calls_change_with_alice_old_password_returns_401(empty_db):
    """bob 用 alice 的旧密码调改密 → 401（旧密码与 bob 真实旧密码不一致）。

    alice 与 bob 密码不同才能构造「body 旧密码是 alice 的、bob 拿来用」的越权探测；
    否则两者共享初始 _STRONG_PWD，body 撞对 bob 自己反而是合法改密。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        # alice 用不同于默认 _STRONG_PWD 的密码，确保 body 注入 alice 旧密码
        # 撞不上 bob 的真实旧密码。
        alice = await _register(c, "alice", password="AliceSpec!1pwd")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]
        alice_before = await _fresh_user("alice")

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                # 用 alice 的旧密码撞 bob → 必然 verify_password 失败 → 401
                "old_password": "AliceSpec!1pwd",
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 401, (
            f"用 alice 旧密码撞 bob 应 401，实际 {r.status_code}：{r.text}"
        )

        alice_after = await _fresh_user("alice")
        assert alice_after.password_hash == alice_before.password_hash, (
            "alice 密码被改动！端点把 body 错旧密码误读为 alice 越权"
        )
        assert verify_password("AliceSpec!1pwd", alice_after.password_hash)


async def test_B2_bob_with_correct_old_password_changes_only_self(empty_db):
    """bob 用自己的旧密码 + 新密码改 → 200，且 alice 完全 unaffected。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        alice = await _register(c, "alice")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]
        alice_before = await _fresh_user("alice")

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 200, r.text

        assert verify_password(_STRONG_PWD_NEW, (await _fresh_user("bobby")).password_hash)
        alice_after = await _fresh_user("alice")
        assert alice_after.password_hash == alice_before.password_hash
        assert verify_password(_STRONG_PWD, alice_after.password_hash)


# ─────────────────────────────────────────────────────────────────────────────
# Group C：路径 / query 参数越权
# ─────────────────────────────────────────────────────────────────────────────


async def test_C1_query_user_id_param_does_not_change_other(empty_db):
    """POST /auth/change-password?user_id=<admin_id> — FastAPI 默认不识别未知 query。
    端点不应接受 query user_id；不论其静默忽略还是 422：admin 的密码必须 unchanged。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        admin = await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]
        admin_id = admin["user"]["id"]
        admin_before = await _fresh_user("admin1")

        r = await c.post(
            f"/api/v1/auth/change-password?user_id={admin_id}",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        # 允许行为：200（query 被忽略，bob 自己被改）/ 422（FastAPI 拒未知 query）。

        admin_after = await _fresh_user("admin1")
        assert admin_after.password_hash == admin_before.password_hash, (
            "admin 的 password_hash 被 query 参数改了——query user_id 注入越权"
        )
        assert verify_password(_STRONG_PWD, admin_after.password_hash)


async def test_C2_path_with_user_segment_is_not_routed(empty_db):
    """POST /auth/change-password/admin — 路径不接 user_id 段，应 404 / 405。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]
        admin_before = await _fresh_user("admin1")

        r = await c.post(
            "/api/v1/auth/change-password/admin",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code in (404, 405), (
            f"路径 /change-password/admin 不该被路由，实际 {r.status_code}：{r.text}"
        )

        admin_after = await _fresh_user("admin1")
        assert admin_after.password_hash == admin_before.password_hash
        assert verify_password(_STRONG_PWD, admin_after.password_hash)


# ─────────────────────────────────────────────────────────────────────────────
# Group D：token 缺失 / 篡改 / 过期
# ─────────────────────────────────────────────────────────────────────────────


async def test_D1_missing_authorization_header_returns_401(empty_db):
    """无 Authorization 头 → 401。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/auth/change-password",
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 401, (
            f"无 token 应 401，实际 {r.status_code}：{r.text}"
        )


async def test_D2_tampered_jwt_sub_field_returns_401(empty_db):
    """篡改 JWT payload 的 sub 字段后 → 签名验失败 → 401。"""
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone
    from app.core.settings import get_settings

    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        admin = await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        bob = await _register(c, "bobby")

        admin_id = admin["user"]["id"]
        admin_before = await _fresh_user("admin1")

        settings = get_settings()
        now = datetime.now(timezone.utc)
        # 用同一个密钥伪造一个指向 admin 的 token；合法密钥即可，但 sub 被改
        forged = pyjwt.encode(
            {
                "sub": admin_id,  # 试图伪装成 admin
                "iat": now,
                "exp": now + timedelta(minutes=10),
                "jti": "forged",
                "iss": "xiaozhi-fde-talk",
                "aud": "xiaozhi-client",
                "pwd_ver": int((admin_before.password_changed_at or now).timestamp()),
                "username": "admin1",
                "role": "admin",
            },
            settings.jwt_secret,
            algorithm="HS256",
        )
        # 改一字符让签名失效
        tampered = forged[:-2] + ("AA" if forged[-2:] != "AA" else "BB")

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {tampered}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 401, (
            f"篡改 sub 的 JWT 应 401（签名失败），实际 {r.status_code}：{r.text}"
        )

        admin_after = await _fresh_user("admin1")
        assert admin_after.password_hash == admin_before.password_hash
        assert verify_password(_STRONG_PWD, admin_after.password_hash)


async def test_D3_expired_jwt_returns_401(empty_db):
    """过期 token（exp 早于当前时间）→ 401。"""
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone
    from app.core.settings import get_settings

    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        bob = await _register(c, "bobby")
        bob_user = bob["user"]
        bob_db = await _fresh_user("bobby")

        settings = get_settings()
        now = datetime.now(timezone.utc)
        expired = pyjwt.encode(
            {
                "sub": bob_user["id"],
                "iat": now - timedelta(hours=2),
                "exp": now - timedelta(hours=1),  # 已过期
                "jti": "expired",
                "iss": "xiaozhi-fde-talk",
                "aud": "xiaozhi-client",
                "pwd_ver": int((bob_db.password_changed_at or now).timestamp()),
                "username": bob_user["username"],
                "role": bob_user["role"],
            },
            settings.jwt_secret,
            algorithm="HS256",
        )

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {expired}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 401, (
            f"过期 JWT 应 401，实际 {r.status_code}：{r.text}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Group E：横向隔离 — pwd_ver bump 真实生效 + 不影响其他用户 token
# ─────────────────────────────────────────────────────────────────────────────


async def test_E1_old_token_revoked_after_self_password_change(empty_db):
    """bob 改密后**用旧 token**调受保护端点 → 401（pwd_ver 吊销）。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]

        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 200, r.text

        r = await c.get(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert r.status_code == 401, (
            f"bob 改密后旧 token 应被 pwd_ver 吊销→401，实际 {r.status_code}：{r.text}"
        )


async def test_E2_other_users_token_unaffected_after_one_change(empty_db):
    """bob 改密后，alice 的 token 仍能正常用 → 200 / 不受牵连。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        alice = await _register(c, "alice")
        bob = await _register(c, "bobby")
        bob_token = bob["access_token"]
        alice_token = alice["access_token"]

        # bob 改密
        r = await c.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "old_password": _STRONG_PWD,
                "new_password": _STRONG_PWD_NEW,
            },
        )
        assert r.status_code == 200, r.text

        # alice 的 token 没被波及，仍可用
        r = await c.get(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert r.status_code == 200, (
            f"alice token 应不被 bob 改密影响，实际 {r.status_code}：{r.text}"
        )

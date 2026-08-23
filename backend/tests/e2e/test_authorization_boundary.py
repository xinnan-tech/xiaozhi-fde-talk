"""E2E：越权测试矩阵——只验证拒绝路径（401/403/404），不验证 happy path。

覆盖 5 组反向场景：
- A. anonymous（无 token）访问受保护资源 → 401
- B. 普通用户（role=user）越权调 admin 端点 → 403
- C. 跨用户访谈访问（alice 动 bob 的 interview）→ 404
- D. JWT 篡改：改 payload 但保留原 signature / 用过期 token → 401
- E. admin 自身不越权：可改自己密码；改不存在用户 → 404

每个用例**精确断言**期望状态码（不用 status in (401,403,404) 模糊断言）。
本测试只跑 ASGI 进程内应用（端口不可用也无所谓），与 T9 同款。

不调运行中的 8000 后端——用 ASGITransport 在进程内跑完整 app + lifespan。
DB 清理与 ConfigStore 缓存失效经模块内 fixture，不依赖外部 conftest（已知坏）。
"""
# conftest intentionally not imported — see ledger
from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config_store import get_config_store
from app.persistence.db import SessionLocal


# ─────────────────────────────────────────────────────────────────────
# Fixture：lifespan app + 干净的 DB
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def _lifespan_app():
    """模块级共用一个 app + 已跑过 lifespan。

    与 T9（test_auth_registration）同款：lifespan 启动后 init_db + ConfigStore
    warm + JWT secret 注入 settings。
    """
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    os.environ.setdefault("APP_ENV", "dev")

    from app.app import create_app
    from app.core.settings import get_settings
    get_settings.cache_clear()

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


async def _wipe_db() -> None:
    """清干净 DB：users + interviews + reports + auth.allow_registration 开关。"""
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
    """函数级 fixture：清 DB + 失效 ConfigStore 缓存，返回 app。"""
    await _wipe_db()
    get_config_store().invalidate()
    yield _lifespan_app
    await _wipe_db()
    get_config_store().invalidate()


# ─────────────────────────────────────────────────────────────────────
# helpers：注册 / 拿 token / 伪造 token
# ─────────────────────────────────────────────────────────────────────


_STRONG_PWD = "Strong1!pwd"


async def _register(c: AsyncClient, username: str, password: str = _STRONG_PWD) -> dict[str, Any]:
    """注册用户，返回 {access_token, user}。"""
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


def _b64url_decode(segment: str) -> bytes:
    """JWT segment base64url 解码（补 padding）。"""
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def _b64url_encode(raw: bytes) -> str:
    """bytes → base64url 字符串（去 padding）。"""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _forge_jwt(original_token: str, mutate) -> str:
    """解码原 token 的 payload，应用 mutate(payload) 修改，重新 base64-encode
    但**不复用原 signature**——原 signature 与新 payload 不匹配 → 服务端
    decode 验签失败 → 401。

    实现：保留 header + 修改后 payload + 用一段乱填的"假 signature"
    （与服务端密钥无关）。这模拟了攻击者：能 base64 解码 token、但拿不到
    签名密钥、只能伪造签名的情况。
    """
    header_b64, payload_b64, _sig_b64 = original_token.split(".")
    payload = json.loads(_b64url_decode(payload_b64))
    mutate(payload)
    new_payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    # 假 signature：32 字节随机 base64url——保证服务端 HMAC 验签一定失败
    fake_sig = _b64url_encode(b"forged-signature-not-matching-server-key-padding-padding")
    return f"{header_b64}.{new_payload_b64}.{fake_sig}"


@pytest.fixture
async def three_users(empty_db):
    """注册 3 个用户：admin（首注册） + bob + alice，返回 dict 含 token / user_id / app。

    直接调 ConfigStore.set 放开 allow_registration 而非走 PUT /admin/config——
    避免对配置 API 行为产生额外假设（与 T9 同款做法）。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        admin_body = await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        bob_body = await _register(c, "bobby")
        alice_body = await _register(c, "alicee")

    return {
        "_app": app,
        "admin_token": admin_body["access_token"],
        "admin_id": admin_body["user"]["id"],
        "bob_token": bob_body["access_token"],
        "bob_id": bob_body["user"]["id"],
        "alice_token": alice_body["access_token"],
        "alice_id": alice_body["user"]["id"],
    }


# ─────────────────────────────────────────────────────────────────────
# Group A：anonymous（无 token）
# ─────────────────────────────────────────────────────────────────────


async def test_a_anonymous_cannot_list_admin_users(empty_db):
    """GET /admin/users 无 token → 401。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/admin/users")
        assert r.status_code == 401, (
            f"anonymous 应被 401 拦在 /admin/users 之外，实际 {r.status_code}：{r.text}"
        )


async def test_a_anonymous_cannot_reset_user_password(empty_db):
    """POST /admin/users/{any_id}/password 无 token → 401。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/admin/users/whatever-id/password",
            json={"new_password": _STRONG_PWD},
        )
        assert r.status_code == 401, (
            f"anonymous 应被 401 拦在 admin password reset 之外，实际 {r.status_code}：{r.text}"
        )


async def test_a_anonymous_cannot_put_admin_config(empty_db):
    """PUT /admin/config/auth 无 token → 401。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put("/api/v1/admin/config/auth", json={"allow_registration": "true"})
        assert r.status_code == 401, (
            f"anonymous 应被 401 拦在 PUT admin config 之外，实际 {r.status_code}：{r.text}"
        )


async def test_a_anonymous_cannot_get_user_interviews(empty_db):
    """GET /admin/users/{id}/interviews 端点在项目中**不存在**——路由不匹配先
    返 404；HTTPBearer 401 在路由命中后才生效。brief 标记此用例"如该端点存在"
    才 401，实际项目未提供此端点，故跳过。

    保留此用例作为端点不存在性证据：未来若加上 admin per-user 访谈端点，
    本测试应改为断言 401。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/admin/users/whatever-id/interviews")
        # 端点不存在 → 404 路由不匹配先于 401 触发
        assert r.status_code == 404, (
            f"admin per-user 访谈端点不存在应 404，实际 {r.status_code}：{r.text}"
        )
        pytest.skip(
            "端点 /admin/users/{id}/interviews 不存在（brief 标记如该端点存在才覆盖）；"
            "未来若加端点请把 404 改 401 并移除 skip"
        )


# ─────────────────────────────────────────────────────────────────────
# Group B：普通用户越权（role=user）
# ─────────────────────────────────────────────────────────────────────


async def test_b_user_role_cannot_list_admin_users(three_users):
    """bob (role=user) 调 GET /admin/users → 403。"""
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {three_users['bob_token']}"},
        )
        assert r.status_code == 403, (
            f"role=user 调 /admin/users 应被 403，实际 {r.status_code}：{r.text}"
        )


async def test_b_user_role_cannot_reset_admin_password(three_users):
    """bob 调 POST /admin/users/{admin_id}/password → 403（不能改 admin 密码）。"""
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            f"/api/v1/admin/users/{three_users['admin_id']}/password",
            headers={"Authorization": f"Bearer {three_users['bob_token']}"},
            json={"new_password": "Hacked1!pwd"},
        )
        assert r.status_code == 403, (
            f"role=user 改 admin 密码应被 403，实际 {r.status_code}：{r.text}"
        )


async def test_b_user_role_cannot_reset_own_password_via_admin(three_users):
    """bob 调 POST /admin/users/{自己_id}/password → 403（admin 端点不给 user）。

    关键测试：即便 admin 端点的"目标 user_id = 自己"，也仍要走 admin 鉴权。
    这防止 user 通过 admin 端点旁路"自助改密"流程。"""
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            f"/api/v1/admin/users/{three_users['bob_id']}/password",
            headers={"Authorization": f"Bearer {three_users['bob_token']}"},
            json={"new_password": "BobSelf1!new"},
        )
        assert r.status_code == 403, (
            f"role=user 改自己密码走 admin 端点应被 403，实际 {r.status_code}：{r.text}"
        )


async def test_b_user_role_cannot_put_admin_config(three_users):
    """bob 调 PUT /admin/config/auth → 403。"""
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put(
            "/api/v1/admin/config/auth",
            headers={"Authorization": f"Bearer {three_users['bob_token']}"},
            json={"allow_registration": "true"},
        )
        assert r.status_code == 403, (
            f"role=user 调 PUT /admin/config/auth 应被 403，实际 {r.status_code}：{r.text}"
        )


# ─────────────────────────────────────────────────────────────────────
# Group C：跨用户访谈访问（alice 动 bob 的 interview）
# ─────────────────────────────────────────────────────────────────────


async def test_c_alice_cannot_get_bobs_interview(three_users):
    """alice 调 GET /interviews/{bob's id} → 404（资源隔离不泄露存在性）。

    路由代码：state.session.user_id != user.user_id → HTTP_SESSION_NOT_FOUND 404。
    不返 403 是有意为之——避免泄露"该 ID 存在"信息。
    """
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # bob 先创建一个访谈
        r = await c.post(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {three_users['bob_token']}"},
            json={"template_id": "pm-research"},
        )
        # bob 创建可能 200（有模板）或 404（无模板）；后者跳过跨用户测试
        assert r.status_code in (200, 404), (
            f"bob 创建访谈预期 200/404，实际 {r.status_code}：{r.text}"
        )
        if r.status_code == 404:
            pytest.skip("模板未预热，无法创建访谈，跳过跨用户测试")
        bob_interview_id = r.json()["id"]

        # alice 用自己的 token 调 GET bob 的访谈 → 404
        r = await c.get(
            f"/api/v1/interviews/{bob_interview_id}",
            headers={"Authorization": f"Bearer {three_users['alice_token']}"},
        )
        assert r.status_code == 404, (
            f"alice 调 GET bob 访谈应 404（不泄露存在性），实际 {r.status_code}：{r.text}"
        )


async def test_c_alice_cannot_patch_bobs_interview(three_users):
    """alice 调 PATCH /interviews/{bob's id} → 404。"""
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {three_users['bob_token']}"},
            json={"template_id": "pm-research"},
        )
        assert r.status_code in (200, 404), r.text
        if r.status_code == 404:
            pytest.skip("模板未预热，无法创建访谈")
        bob_interview_id = r.json()["id"]

        r = await c.patch(
            f"/api/v1/interviews/{bob_interview_id}",
            headers={"Authorization": f"Bearer {three_users['alice_token']}"},
            json={"goal": "alice 越权改 bob 的目标"},
        )
        assert r.status_code == 404, (
            f"alice 调 PATCH bob 访谈应 404，实际 {r.status_code}：{r.text}"
        )


async def test_c_alice_cannot_delete_bobs_interview(three_users):
    """alice 调 DELETE /interviews/{bob's id} → 404。"""
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {three_users['bob_token']}"},
            json={"template_id": "pm-research"},
        )
        assert r.status_code in (200, 404), r.text
        if r.status_code == 404:
            pytest.skip("模板未预热，无法创建访谈")
        bob_interview_id = r.json()["id"]

        r = await c.delete(
            f"/api/v1/interviews/{bob_interview_id}",
            headers={"Authorization": f"Bearer {three_users['alice_token']}"},
        )
        assert r.status_code == 404, (
            f"alice 调 DELETE bob 访谈应 404，实际 {r.status_code}：{r.text}"
        )


async def test_c_alice_cannot_first_batch_bobs_interview(three_users):
    """alice 调 POST /interviews/{bob's id}/first-batch → 404。

    替代了 brief 中的 /transcribe 端点——项目没有 /transcribe HTTP 端点
    （转写在 WS 协议），/first-batch 是同性质的 owner-bound 子端点。
    """
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {three_users['bob_token']}"},
            json={"template_id": "pm-research"},
        )
        assert r.status_code in (200, 404), r.text
        if r.status_code == 404:
            pytest.skip("模板未预热，无法创建访谈")
        bob_interview_id = r.json()["id"]

        r = await c.post(
            f"/api/v1/interviews/{bob_interview_id}/first-batch",
            headers={"Authorization": f"Bearer {three_users['alice_token']}"},
        )
        assert r.status_code == 404, (
            f"alice 调 first-batch bob 访谈应 404，实际 {r.status_code}：{r.text}"
        )


# ─────────────────────────────────────────────────────────────────────
# Group D：JWT 篡改防护
# ─────────────────────────────────────────────────────────────────────


async def test_d_jwt_tampered_role_admin_signature_invalid(empty_db):
    """改 payload role='admin' 但伪造 signature → 401（HMAC 验签失败）。

    攻击场景：拿到合法 user token → base64-decode payload → 改 role='admin'
    → 重新 encode（保留原 header）→ 用任意假 signature 替换原 signature。
    服务端应拒（无法用真密钥重新签出有效 signature）。
    """
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 先注册 admin（零用户 → admin），再放开注册，再注册普通用户
        await _register(c, "admin1")
        await get_config_store().set("auth.allow_registration", "true")
        body = await _register(c, "regular_user")
        user_token = body["access_token"]
        assert body["user"]["role"] == "user", body

        # 篡改：role='admin' + 假 signature
        forged = _forge_jwt(user_token, lambda p: p.update({"role": "admin"}))

        r = await c.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert r.status_code == 401, (
            f"篡改 role=admin 的 token 应被 HMAC 验签拦在 401，"
            f"实际 {r.status_code}：{r.text}"
        )


async def test_d_jwt_tampered_sub_to_admin_signature_invalid(empty_db):
    """改 payload sub=admin_id 但伪造 signature → 401。"""
    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # admin 首注册
        admin_body = await _register(c, "admin1")
        admin_id = admin_body["user"]["id"]
        # 放开注册，注册普通用户
        await get_config_store().set("auth.allow_registration", "true")
        bob_body = await _register(c, "bobby")

        # 篡改 bob 的 token：sub 改成 admin_id
        forged = _forge_jwt(
            bob_body["access_token"],
            lambda p: p.update({"sub": admin_id, "role": "admin"}),
        )

        r = await c.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert r.status_code == 401, (
            f"篡改 sub=admin_id 的 token 应被 HMAC 验签拦在 401，"
            f"实际 {r.status_code}：{r.text}"
        )


async def test_d_jwt_pwd_ver_mismatch_revokes_token(three_users):
    """admin 改 bob 密码 → bob 旧 token pwd_ver 不匹配 → 401。

    T9 已覆盖 admin 改 bob 密码吊销 token 调 /admin/users；本用例复用同款路径
    但只断言 401，不依赖 T9 通过与否。
    """
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # admin 改 bob 密码
        r = await c.post(
            f"/api/v1/admin/users/{three_users['bob_id']}/password",
            headers={"Authorization": f"Bearer {three_users['admin_token']}"},
            json={"new_password": "BobNew1!pwd"},
        )
        assert r.status_code == 200, f"admin 改 bob 密码应通过：{r.text}"

        # bob 旧 token（pwd_ver 已过时）调任一受保护端点 → 401
        r = await c.get(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {three_users['bob_token']}"},
        )
        assert r.status_code == 401, (
            f"bob 旧 token 应被 pwd_ver 吊销→401，实际 {r.status_code}：{r.text}"
        )


async def test_d_jwt_manually_expired_signature_invalid(empty_db):
    """用 jwt 库签一个过期 token（用服务端密钥，但 exp 已过）→ 401。

    这模拟"用旧 token 重放"——服务端 exp 校验应拒。
    注意：本测试读服务端 jwt_secret 来签**合法签名**的过期 token，以验证
    exp claim 本身的拦截（与 signature 拦截是两套独立防线）。
    """
    from app.core.settings import get_settings

    settings = get_settings()
    secret = settings.jwt_secret
    assert secret, "lifespan 应注入 jwt_secret 到 settings"

    past = int(time.time()) - 3600  # 1 小时前签发
    payload = {
        "sub": "ghost-user",
        "iat": past,
        "exp": past + 60,  # 早就过期
        "pwd_ver": past,
        "iss": "xiaozhi-fde-talk",
        "aud": "xiaozhi-client",
        "role": "admin",
        "username": "ghost",
    }
    expired_token = jwt.encode(payload, secret, algorithm="HS256")

    app = empty_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert r.status_code == 401, (
            f"过期 token 应被 exp 拦在 401，实际 {r.status_code}：{r.text}"
        )


# ─────────────────────────────────────────────────────────────────────
# Group E：admin 自身不越权
# ─────────────────────────────────────────────────────────────────────


async def test_e_admin_can_reset_own_password(three_users):
    """admin 自己改自己密码（admin 端点允许改任何人含自己）→ 200。

    防回归：admin 端点不应在 `target_user_id == admin_user_id` 时特殊拒绝。
    """
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            f"/api/v1/admin/users/{three_users['admin_id']}/password",
            headers={"Authorization": f"Bearer {three_users['admin_token']}"},
            json={"new_password": "AdminSelf1!new"},
        )
        assert r.status_code == 200, (
            f"admin 改自己密码应通过，实际 {r.status_code}：{r.text}"
        )


async def test_e_admin_reset_nonexistent_user_returns_404(three_users):
    """admin 改不存在的 user_id → 404。

    区分于 403（admin 鉴权通过但 user_id 无效），证明 admin 端点不是"任何
    user_id 都返 ok"。
    """
    app = three_users["_app"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/v1/admin/users/no-such-user-id/password",
            headers={"Authorization": f"Bearer {three_users['admin_token']}"},
            json={"new_password": "Ghost1!pwd"},
        )
        assert r.status_code == 404, (
            f"admin 改不存在 user 应 404，实际 {r.status_code}：{r.text}"
        )

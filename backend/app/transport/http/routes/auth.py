"""鉴权路由。

HttpOnly cookie 模型：access / refresh 经 ``authorized-token`` / ``refresh-token``
cookie 下发（XSS 防御主路径），body 仍返回 token 供兼容路径（scripts / 测试）。
- /auth/refresh：一次性 rotation + reuse 检测，会话状态落 refresh_sessions 表
  （多 worker 共享、重启不丢，见 persistence/repositories/refresh_session.py）。
- /auth/logout：撤销 refresh jti + 清两个 cookie。
- /auth/me：cookie 鉴权，供前端 main.ts 启动前 bootstrap。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import jwt as pyjwt
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_store import get_auth_runtime_config, get_config_store
from app.core.exceptions import AuthError
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.core.password_policy import validate_password_strength
from app.core.retry import RateLimiter
from app.core.security import verify_password_async
from app.domain.auth import CurrentUser
from app.persistence.db import engine, get_db
from app.persistence.models import User
from app.persistence.repositories.refresh_session import (
    classify_refresh_session,
    refresh_session_repo,
)
from app.persistence.repositories.user import user_repo
from app.services.auth.cookies import (
    clear_auth_cookies,
    set_access_cookie,
    set_refresh_cookie,
)
from app.services.auth.service import authenticate_user, register_user as svc_register
from app.services.auth.token import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.transport.http.dependencies import get_current_user
from app.transport.http.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegistrationStatusResponse,
    UserInfo,
)
from app.transport.base import extract_auth, token_from_subprotocols

logger = logging.getLogger(__name__)

router = APIRouter()

# DB 方言是进程级常量（engine 随 settings.db_url 构建一次）：SQLite 需显式
# BEGIN IMMEDIATE 抢写锁串行化写事务；PG/MySQL 靠默认隔离级 + 唯一约束收口。
_IS_SQLITE = engine.dialect.name == "sqlite"

_login_limiter = RateLimiter(capacity=5, refill_per_hour=300)
# 注册限流比登录更严：首用户自动获得 admin，必须防止枚举/抢首注册。
# 同样的 (ip, username) 桶复用同一份限流逻辑；register 端点自身的校验失败
# （弱密码 / 两次密码不一致 / 重复 username）也消耗令牌——避免暴力扫 username
# 与弱密码走绕过路径。
_register_limiter = RateLimiter(capacity=3, refill_per_hour=60)
# 注册另起一条按 IP 单键的桶：(ip, username) 双键会被 IP 池绕过（每个新 IP
# 跟同一组 username 组合都是新桶），单 IP 桶卡住「同一出口 IP 上无论换 username
# 都不让无限制打」。capacity=5、refill_per_hour=20 比双键宽——双键继续把单
# username 暴力打严住，IP 桶负责守住 IP 池兜底。
_register_ip_limiter = RateLimiter(capacity=5, refill_per_hour=20)
# /auth/refresh 限流按 ip 单桶：refresh 通常由前端 axios 拦截器自动触发，
# 频繁度高于登录；按用户限会把自动刷新路径锁死。纯 ip 限足够挡住外网滥用。
_refresh_limiter = RateLimiter(capacity=30, refill_per_hour=600)
# change-password 复用与 login 同款限流参数：capacity=5, refill_per_hour=300。
# 按 (client_ip + user_id) 做 key，与 login 的 (client_ip + username) 错开但体量对等。
_change_pwd_limiter = RateLimiter(capacity=5, refill_per_hour=300)
# /auth/me 限流：main.ts 启动 + router.beforeEach 首跳 + 401 重试都会调。
# 缺桶的话攻击者可枚举用户（端点返 username + role）或对 DB 施压。
_auth_me_limiter = RateLimiter(capacity=60, refill_per_hour=3600)


def _reset_for_test() -> None:
    """清空登录 / 注册限流桶 + refresh token 撤销表。仅 settings.env in {"test","dev"} 时生效。

    单元/集成测试用例间需要隔离限流状态；模块级 RateLimiter 跨用例持续累加，
    不暴露 reset 的话测试要么 sleep 等令牌再生（慢），要么依赖运气。生产环境
    误调会清掉所有封禁桶，故显式 env 守门——只放行 dev/test，禁止 prod。
    """
    from app.core.settings import get_settings

    if get_settings().env not in ("test", "dev"):
        return
    _login_limiter._buckets.clear()
    _register_limiter._buckets.clear()
    _register_ip_limiter._buckets.clear()
    _refresh_limiter._buckets.clear()
    _change_pwd_limiter._buckets.clear()
    _auth_me_limiter._buckets.clear()
    # refresh_sessions 表无需清：jti PK 随机不跨用例碰撞，user_id 每用例
    # 随机 uuid，残留行对后续用例不可见。


def _trusted_proxy_ips() -> set[str]:
    """解析 settings.trusted_proxies 为 IP 集合。

    缓存：settings 是 lru_cache 单例，CSV 不变就一直用同一份集合。env 改了
    需要重启进程（限流桶跨重启本来就无意义——重启清空）。
    """
    from app.core.settings import get_settings

    csv = get_settings().trusted_proxies.strip()
    if not csv:
        return set()
    return {x.strip() for x in csv.split(",") if x.strip()}


def _client_ip(request: Request) -> str:
    """取真实客户端 IP，必须先验前置代理可信才读 XFF。

    直连：socket 地址即客户端 IP，永远可信。
    经反向代理：socket 是代理地址，不能直接当客户端用——必须验 request.client.host
    在 trusted_proxies 白名单里、且 XFF 首跳存在，才采用 XFF。攻击者塞伪造
    XFF 时，socket 不是 trusted proxy（如公网直接打后端），白名单未命中就
    走 socket 路径，伪造 XFF 被忽略。

    CIDR（如 10.0.0.0/8）不支持——白名单只列裸 IP。理由：1) 内部代理一般就
    几台 LB/反代，IP 数量有限；2) CIDR 解析要拉 ipaddress 库增加依赖面；
    3) 上层 nginx 已可做白名单 CIDR 收敛。
    """
    socket_ip = request.client.host if request.client else "unknown"
    if socket_ip not in _trusted_proxy_ips():
        return socket_ip
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return socket_ip


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """登录：HttpOnly cookie 下发 access + refresh，响应体仅含 user。
    """
    key = f"{_client_ip(request)}:{req.username}"
    if not _login_limiter.try_acquire(key):
        raise I18nError(Keys.HTTP_AUTH_RATE_LIMITED, http_status=429)
    user = await authenticate_user(db, req.username, req.password)
    if user is None:
        raise I18nError(Keys.HTTP_AUTH_INVALID_CREDENTIALS, http_status=401)
    state = await user_repo.get_auth_state(user.user_id)
    pwd_changed_at = state.password_changed_at
    # 历史用户 password_changed_at 可能为 None（迁移前回填的边缘场景）；
    # 退化到当前时间——保证 token 必然签出，pwd_ver 与 DB 始终能比对。
    # naive datetime 统一当 UTC 解释，与 extract_auth 比对端对齐——
    # 否则 CI UTC 下 pwd_ver 假阳性相等、改密后 token 漏吊销。
    if pwd_changed_at and pwd_changed_at.tzinfo is None:
        pwd_changed_at = pwd_changed_at.replace(tzinfo=timezone.utc)
    pwd_ver = int(pwd_changed_at.timestamp()) if pwd_changed_at else int(time.time())
    extra = {"username": user.username, "role": user.role}
    access_token = await create_access_token(
        subject=user.user_id, pwd_ver=pwd_ver, extra=extra,
    )
    refresh_token, _refresh_jti, _refresh_exp = await create_refresh_token(
        subject=user.user_id, pwd_ver=pwd_ver, extra=extra,
    )
    # refresh 会话登记簿：logout 撤销 / rotation / reuse 检测的事实源。
    await refresh_session_repo.register(
        db, jti=_refresh_jti, user_id=user.user_id, expires_at=_refresh_exp,
    )
    # HttpOnly cookie 下发（主路径，XSS 防御）。同时把 token 也写到 body 给兼容
    # 路径（scripts / chaos.py / Authorization Bearer 测试）：前端主路径走 cookie，
    # 不读 body token（Pinia 也不再持有），body token 走兼容用途。
    await set_access_cookie(response, access_token)
    await set_refresh_cookie(response, refresh_token)
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserInfo(id=user.user_id, username=user.username, role=user.role),
    )


@router.get("/auth/registration-status", response_model=RegistrationStatusResponse)
async def registration_status(db: AsyncSession = Depends(get_db)) -> RegistrationStatusResponse:
    """公开端点：零用户强制 allow_registration=true（首用户注册路径必须通畅）；
    有用户时按 auth.allow_registration key 当前值返。

    响应体仅暴露 allow_registration，不暴露 user_count / has_admin（防侦察）。
    接口失败 / 超时由前端降级显示"暂不可用，请稍后重试"。
    """
    count = (await db.execute(select(func.count(User.id)))).scalar_one()
    if count == 0:
        return RegistrationStatusResponse(allow_registration=True)
    cfg_val = await get_config_store().get("auth.allow_registration")
    return RegistrationStatusResponse(allow_registration=(cfg_val == "true"))


@router.post("/auth/register", response_model=LoginResponse)
async def register(
    req: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """注册 + 自动登录（公开端点）。HttpOnly cookie 下发。

    单一事务：先 `async with db.begin()`，再 `await svc_register(db, ...)`；
    register_user 内部不管理事务边界（dialect 锁 + count + insert 必须同事务）。

    限流先于任何校验：防止扫 username / 撞首注册。桶与登录同款
    `_client_ip(request):req.username`，失败校验也消耗令牌。

    首用户 admin 并发安全（SQLite）：
    AsyncSession.autobegin 默认发 BEGIN DEFERRED，仅在首次写操作时升级为写锁
    ——对 SELECT COUNT + INSERT 双请求竞争（都见 count=0 → 都成 admin）太晚。
    本路由显式 BEGIN IMMEDIATE 抢写锁首跳串行化：注册限流 + 写锁 + username
    unique 约束三层兜底。PG/MySQL 由默认隔离级别（REPEATABLE READ /
    READ COMMITTED）+ unique 约束的 INSERT 排他锁自然收口，无须此 hack。

    弱密码校验移到 service.register_user（保证 CLI / admin 代注册同受约束），
    本路由只做 confirm_password 比对。
    """
    # 限流先于 confirm 比对与弱密码校验：失败路径同样消耗令牌，避免枚举绕路
    rl_key = f"{_client_ip(request)}:{req.username}"
    if not _register_limiter.try_acquire(rl_key):
        raise I18nError(Keys.HTTP_AUTH_RATE_LIMITED, http_status=429)
    # IP 单键桶：防 IP 池换源绕开 (ip, username) 双键——换 IP 后每个 username
    # 仍是新组合的双键桶，但 IP 桶基于同一出口 IP 仍命中。先 IP 后双键：IP 桶
    # 比双键更宽松（capacity=5 vs 3），先卡 IP 池滥用，双键继续卡单 username 暴力。
    if not _register_ip_limiter.try_acquire(_client_ip(request)):
        raise I18nError(Keys.HTTP_AUTH_RATE_LIMITED, http_status=429)

    if req.password != req.confirm_password:
        raise I18nError(Keys.AUTH_PASSWORD_MISMATCH, http_status=400)

    # SQLite 路径：禁用 autobegin → 显式 BEGIN IMMEDIATE 抢写锁首跳
    # PG/MySQL 路径：依赖默认隔离级别 + username unique 约束串行化
    if _IS_SQLITE:
        db.autobegin = False
        await db.execute(text("BEGIN IMMEDIATE"))

    try:
        try:
            if _IS_SQLITE:
                current = await svc_register(db, req.username, req.password)
                await db.commit()
            else:
                async with db.begin():
                    current = await svc_register(db, req.username, req.password)
        except IntegrityError:
            await db.rollback()
            raise I18nError(Keys.AUTH_USERNAME_TAKEN, http_status=409)
    finally:
        if _IS_SQLITE:
            db.autobegin = True

    # 签发 token（含 pwd_ver，参考 login 路由 + Task 2 改密吊销约定）
    state = await user_repo.get_auth_state(current.user_id)
    pwd_changed_at = state.password_changed_at
    # 历史用户 password_changed_at 可能为 None；退化到当前时间——保证 token
    # 必然签出，pwd_ver 与 DB 始终能比对（login 路由同款）。
    # naive datetime 统一当 UTC 解释，与 extract_auth 比对端对齐——
    # 否则 CI UTC 下 pwd_ver 假阳性相等、改密后 token 漏吊销。
    if pwd_changed_at and pwd_changed_at.tzinfo is None:
        pwd_changed_at = pwd_changed_at.replace(tzinfo=timezone.utc)
    pwd_ver = int(pwd_changed_at.timestamp()) if pwd_changed_at else int(time.time())
    extra = {"username": current.username, "role": current.role}
    access_token = await create_access_token(
        subject=current.user_id, pwd_ver=pwd_ver, extra=extra,
    )
    refresh_token, _refresh_jti, _refresh_exp = await create_refresh_token(
        subject=current.user_id, pwd_ver=pwd_ver, extra=extra,
    )
    await refresh_session_repo.register(
        db, jti=_refresh_jti, user_id=current.user_id, expires_at=_refresh_exp,
    )
    await set_access_cookie(response, access_token)
    await set_refresh_cookie(response, refresh_token)
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserInfo(id=current.user_id, username=current.username, role=current.role),
    )


# ─────────────────────────────────────────────────────────────────────
# refresh token / logout 端点（HttpOnly cookie 模型）
# ─────────────────────────────────────────────────────────────────────

def _read_refresh_cookie(request: Request) -> str | None:
    """从 cookie 取 refresh_token。无 cookie 返 None，由调用方按需报 401。"""
    return request.cookies.get("refresh-token")


@router.post("/auth/refresh", status_code=200)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用 refresh token（来自 cookie）一次性换新 access + 新 refresh（rotation）。

    - token 由 ``refresh-token`` cookie 携带；新 refresh 经 Set-Cookie 轮换，
      body 同步返回给兼容路径（scripts / 测试）。
    - 旧 jti 置 rotated：60s grace 窗内重放视为多 tab 并发放行；窗外重放
      = reuse = 视同泄露 → 撤销该用户全部 refresh session + 告警。
    - 并发安全：SQLite 用 BEGIN IMMEDIATE 串行化；PG/MySQL 靠默认隔离级
      + refresh_sessions jti 主键约束自然收口。
    """
    if not _refresh_limiter.try_acquire(_client_ip(request)):
        raise I18nError(Keys.HTTP_AUTH_RATE_LIMITED, http_status=429)
    refresh_token = _read_refresh_cookie(request)
    if not refresh_token:
        # 401 + code：与「过期 / 撤销」同语义分支，前端按 401 走清 cookie 流程。
        raise I18nError(Keys.AUTH_REFRESH_INVALID, http_status=401)
    # JWT decode + 字段校验（无 IO）放在 BEGIN IMMEDIATE 之前：401 不抢写锁，
    # 快速失败路径无序列化开销。
    try:
        raw_payload = decode_token(refresh_token)
    except pyjwt.ExpiredSignatureError:
        raise I18nError(Keys.AUTH_REFRESH_EXPIRED, http_status=401)
    except pyjwt.InvalidTokenError:
        raise I18nError(Keys.AUTH_REFRESH_INVALID, http_status=401)
    if raw_payload.get("type") != "refresh":
        raise I18nError(Keys.AUTH_REFRESH_INVALID, http_status=401)
    # exp 必须在位：PyJWT 不强制 exp claim，缺 exp 的（伪造）token 靠下面的
    # ["exp"] 索引会 KeyError → 500，且本身永不过期。与 logout 侧的 exp 检查对称。
    if not (
        raw_payload.get("jti") and raw_payload.get("sub")
        and raw_payload.get("exp") is not None
        and raw_payload.get("pwd_ver") is not None
    ):
        raise I18nError(Keys.AUTH_REFRESH_INVALID, http_status=401)

    if _IS_SQLITE:
        db.autobegin = False
        await db.execute(text("BEGIN IMMEDIATE"))
    try:
        # pwd_ver 核对（DB 读 + 改密吊销）——与 transport/base.py::get_current_user
        # 同款。改密 → DB bump → 旧 refresh 的 claim 视为同 jti 撤销同处理，
        # 否则改密后旧 refresh 还能换新 access，等于改密吊销绕过。
        state = await user_repo.get_auth_state(raw_payload["sub"])
        if state.password_changed_at is None:
            raise I18nError(Keys.AUTH_REFRESH_REVOKED, http_status=401)
        pwd_changed_at = state.password_changed_at
        if pwd_changed_at.tzinfo is None:
            pwd_changed_at = pwd_changed_at.replace(tzinfo=timezone.utc)
        if int(pwd_changed_at.timestamp()) != int(raw_payload["pwd_ver"]):
            raise I18nError(Keys.AUTH_REFRESH_REVOKED, http_status=401)

        user_id = raw_payload["sub"]
        jti = raw_payload["jti"]
        cur_pwd_ver = int(raw_payload["pwd_ver"])
        # extra 从 DB 快照构造，不拷旧 payload 的 role/username——旧 claim 可能已
        # 与 DB 不符（降级场景），拷贝会把过期权限续进新 access。
        extra = {"username": state.username or "", "role": state.role or "user"}

        # rotation 防线：行状态机决定本次 refresh 走向——
        # reuse（grace 窗外旧 jti 重放）= 视同泄露，撤销该用户全部 session；
        # revoked（显式 logout / 已被全员击杀）= 401；valid（active / grace 窗内 /
        # legacy 无行）= 继续走 rotation。
        row = await refresh_session_repo.get(db, jti)
        cfg = await get_auth_runtime_config()
        verdict = classify_refresh_session(
            row, grace_seconds=cfg["refresh_grace_seconds"],
        )
        if verdict == "reuse":
            # known trade-off：并发在途 rotate mint 的新 jti 不在本次 revoke 范围，下次 reuse 检测收口。
            killed = await refresh_session_repo.revoke_all_for_user(db, user_id)
            logger.warning(
                "refresh token reuse detected: user=%s jti=%s（grace 窗外重放），"
                "已撤销该用户全部 refresh session（%d 行）——疑似 token 泄露",
                user_id, jti, killed,
            )
            raise I18nError(Keys.AUTH_REFRESH_REVOKED, http_status=401)
        if verdict == "revoked":
            raise I18nError(Keys.AUTH_REFRESH_REVOKED, http_status=401)

        new_access = await create_access_token(
            subject=user_id, pwd_ver=cur_pwd_ver, extra=extra,
        )
        new_refresh, new_jti, new_exp = await create_refresh_token(
            subject=user_id, pwd_ver=cur_pwd_ver, extra=extra,
        )
        old_exp = datetime.fromtimestamp(raw_payload["exp"], tz=timezone.utc)
        try:
            await refresh_session_repo.rotate(
                db, old_jti=jti, old_row=row, old_expires_at=old_exp,
                user_id=user_id, new_jti=new_jti, new_expires_at=new_exp,
            )
        except ValueError as e:
            # 条件 UPDATE 输给并发写（logout / reuse 击杀抢先）：token 已死，
            # 按 revoked 语义 401；warning 保留 invariant 信号。
            logger.warning("rotate 竞争失败 jti=%s user=%s: %s", jti, user_id, e)
            raise I18nError(Keys.AUTH_REFRESH_REVOKED, http_status=401)
    finally:
        if _IS_SQLITE:
            # 异常路径显式回滚、立即释放 BEGIN IMMEDIATE 写锁（不依赖 get_db
            # teardown 的隐式 rollback）；成功路径 rotate() 已 commit，此处 no-op。
            await db.rollback()
            db.autobegin = True
    await set_access_cookie(response, new_access)
    await set_refresh_cookie(response, new_refresh)
    # body 里也返 token，给兼容路径使用（scripts / 测试）。
    return {
        "ok": True,
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


@router.post("/auth/logout", status_code=200)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """撤销 refresh token jti（来自 cookie，写 refresh_sessions 表）+ 清两个 cookie。

    撤销落 DB：进程重启不丢（内存 set 会随重启清零）；多 worker 共享。
    无行的 legacy token（迁移前签发）补登记 revoked 行，logout 语义不回退。

    不强制 access token 鉴权：能拿到 refresh token 本身已是「合法持有者」
    （refresh 与 access 一起下发）。refresh 自身过期 / 非法也返 200，避免
    用 freshness 探查内部状态。DB 撤销失败返 503 且不清 cookie（fail-closed，
    撤销落库才算登出成功，客户端可重试）。

    不限流：端点幂等（无 cookie / 过期 / 非法一律 200），无任何成功语义
    可被滥用。曾与 refresh 共享 _refresh_limiter IP 桶，攻击者对单 IP
    高频刷 logout 即可耗尽桶并挤掉该 IP 合法用户 axios 拦截器自动触发的
    401→refresh 路径——这是 DoS，删桶彻底封堵。
    """
    refresh_token = _read_refresh_cookie(request)
    if refresh_token:
        try:
            payload = decode_token(refresh_token)
            jti = payload.get("jti")
            sub = payload.get("sub")
            exp = payload.get("exp")
            # exp/sub 缺失说明不是本系统签的 refresh，不登记（同垃圾 token 处理）
            if jti and sub and exp:
                # SQLite：显式 BEGIN IMMEDIATE 抢写锁首跳串行化——避免与并发
                # /auth/refresh 的 rotate() 写回撞车（lost-update）+ legacy token
                # refresh 补登记的 PK 冲突。PG/MySQL 走默认隔离级收口。
                if _IS_SQLITE:
                    db.autobegin = False
                    await db.execute(text("BEGIN IMMEDIATE"))
                try:
                    await refresh_session_repo.revoke_by_jti(
                        db, jti=jti, user_id=sub,
                        expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
                    )
                except Exception as e:
                    # fail-closed：撤销没落库就不算登出成功。此时不清 cookie——
                    # 客户端保留 token 可重试，DB 恢复后重试即真正撤销；
                    # 若清了 cookie 返 200，用户以为已登出，行仍 active，
                    # 持有该 token 的一方（含被盗场景）在 TTL 内照常可用。
                    # 注意 DB 不可用期间 refresh 同样读不了表，不存在「宕机
                    # 窗口内 token 被续期」，风险在恢复之后。
                    raise I18nError(
                        Keys.AUTH_LOGOUT_REVOCATION_FAILED, http_status=503,
                    ) from e
                finally:
                    if _IS_SQLITE:
                        # 同 refresh 路由：撤销失败路径立即释放写锁；
                        # 成功路径 revoke_by_jti 已 commit，此处 no-op。
                        await db.rollback()
                        db.autobegin = True
        except pyjwt.InvalidTokenError:
            # refresh 过期 / 非法 → 也算"清"，直接清 cookie，返 200 避免探查。
            pass
    clear_auth_cookies(response)
    return {"ok": True}


@router.post("/auth/change-password", status_code=200)
async def change_password(
    body: ChangePasswordRequest,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """普通用户自助改密：验证旧密码 + 写新密码 + bump password_changed_at。

    不限 admin——任何持有效 token 的登录用户都能调。复用 user_repo.update_password_auto
    （自带事务 + 失效 _pwd_cache）→ 旧 token 的 pwd_ver 不匹配 → 立即吊销。

    旧密码错误 → 401；新密码强度不合规 → 400（validate_password_strength 抛 I18nError）。
    """
    key = f"{_client_ip(request)}:{current.user_id}"
    if not _change_pwd_limiter.try_acquire(key):
        raise I18nError(Keys.HTTP_AUTH_RATE_LIMITED, http_status=429)
    user = await user_repo.get_by_id(db, current.user_id)
    if user is None or not await verify_password_async(body.old_password, user.password_hash):
        raise I18nError(Keys.HTTP_AUTH_INVALID_CREDENTIALS, http_status=401)
    validate_password_strength(body.new_password)
    # 走 update_password_auto：独立 Session + 刷 password_changed_at + _pwd_cache.pop
    # 复用 admin 改密端点同款路径，避免两条密码写路径并存导致行为漂移。
    ok = await user_repo.update_password_auto(user.username, body.new_password)
    if not ok:
        # 极窄边界：token 解析成功但 user 在此期间被删；返 401 提示重新登录。
        raise I18nError(Keys.HTTP_AUTH_INVALID_CREDENTIALS, http_status=401)
    return {"ok": True}


@router.get("/auth/me", response_model=UserInfo)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserInfo:
    """当前登录用户信息（cookie 鉴权）。供前端 main.ts 启动前 bootstrap 用：
    浏览器 F5 后 cookie 仍在但内存已清，前端调本接口从 cookie 重建 Pinia 状态。

    鉴权：从 cookie 取 access_token；缺失 / 无效 → 401（前端按未登录走）。

    限流：按 IP（capacity=60/h）。main.ts 启动 + router.beforeEach 首跳 +
    401 重试都会调一次，缺桶的话攻击者可枚举用户（端点返 username + role）
    或对 DB 施压。
    """
    if not _auth_me_limiter.try_acquire(_client_ip(request)):
        raise I18nError(Keys.HTTP_AUTH_RATE_LIMITED, http_status=429)
    access_token = request.cookies.get("authorized-token")
    if not access_token:
        raise I18nError(Keys.HTTP_AUTH_NOT_AUTHENTICATED, http_status=401)
    try:
        current = await extract_auth(access_token)
    except AuthError:
        # 仅 AuthError（签名错 / 过期 / pwd_ver 不一致）吞成 401。DB / config_store
        # 等其他异常向上抛 500——前端 bootstrapSession 据 5xx 走 transient_error
        # 不动 Pinia；如果一并吞成 401，bootstrapSession 会清 Pinia + 跳 /home，
        # 用户被静默踢出 + 监控看不到任何 5xx 信号。
        raise I18nError(Keys.HTTP_AUTH_INVALID_CREDENTIALS, http_status=401)
    return UserInfo(id=current.user_id, username=current.username, role=current.role or "user")
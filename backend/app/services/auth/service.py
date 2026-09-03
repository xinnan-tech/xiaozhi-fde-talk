"""鉴权业务逻辑。

密码哈希用 core/security，用户查询走 Repository。
返回 domain.CurrentUser（不暴露 ORM User 到 services/transport）。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_store import get_config_store
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.core.password_policy import validate_password_strength
from app.core.security import hash_password, hash_password_async, verify_password_async
from app.domain.auth import CurrentUser
from app.persistence.models import User
from app.persistence.repositories.user import user_repo

# 模块级预计算 dummy hash：bcrypt cost=12（~1.2s on this system）。
# 用于时序均衡——确保「用户不存在」路径与「密码错误」路径执行相同量的 bcrypt 运算。
_DUMMY_HASH: str = hash_password("__timing_dummy_user_does_not_exist__")


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> Optional[CurrentUser]:
    # user_repo.get_by_username 内部已 .lower()，service 无需再归一
    user = await user_repo.get_by_username(db, username)
    if user is None:
        # 时序均衡：用户不存在时也跑一次 bcrypt，与「密码错误」路径对称，
        # 使攻击者无法通过响应时间区分用户是否存在。
        await verify_password_async(password, _DUMMY_HASH)
        return None
    # 密码错误时也跑一次 bcrypt（与用户不存在路径对称的 1 次 bcrypt），
    # verify_password_async 内部 catch ValueError/TypeError → return False，
    # 异常路径极快但不影响均衡。
    if not await verify_password_async(password, user.password_hash):
        return None
    return CurrentUser(user_id=user.id, username=user.username, role=user.role or "user")


async def register_user(db: AsyncSession, username: str, password: str) -> CurrentUser:
    """注册新用户。首用户→admin；后续 user 受 allow_registration 控制。

    **整段在调用方已开的事务内执行**（含 dialect 锁 + SELECT COUNT + INSERT）。
    调用方负责事务边界（FastAPI 路由层显式 `async with db.begin()`）。

    弱密码校验在此处（不只路由层），保证 admin 代注册 / 脚本 / CLI 调 register_user
    同样受强密码策略约束。
    """
    # 1. 弱密码校验（提前，事务开始前可省一次锁开销）
    validate_password_strength(password)

    # 2. dialect 锁 —— 跨方言可靠：PG 用 advisory_xact_lock（事务结束自动释放）；
    #    MySQL 用 GET_LOCK（连接级，需显式 RELEASE_LOCK）；SQLite 由调用方走
    #    BEGIN IMMEDIATE（execution_options(isolation_level="IMMEDIATE")）。
    #    注：db.bind 在 SQLAlchemy 2 async 下常为 None，必须走 db.get_bind()。
    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind is not None else "sqlite"
    if dialect_name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(7423912)"))
        return await _do_register(db, username, password)
    if dialect_name == "mysql":
        # GET_LOCK 是连接级，需显式释放；事务回滚时锁也会随连接回收，
        # 但显式 try/finally 防止锁漏导致后续请求阻塞。
        await db.execute(text("SELECT GET_LOCK('register_first_user', 5)"))
        try:
            return await _do_register(db, username, password)
        finally:
            await db.execute(text("SELECT RELEASE_LOCK('register_first_user')"))
    # SQLite / 未知方言：直接执行（SQLite 由路由层 BEGIN IMMEDIATE 兜底）。
    return await _do_register(db, username, password)


async def _do_register(db: AsyncSession, username: str, password: str) -> CurrentUser:
    """register_user 的核心逻辑，锁内执行。"""
    # 3. 用户数判断（dialect 锁之后）
    count = (await db.execute(select(func.count(User.id)))).scalar_one()

    # 4. allow_registration 管控（仅当 user_count>0 时；零用户强制放行）
    if count > 0:
        cfg_val = await get_config_store().get("auth.allow_registration")
        if cfg_val != "true":
            raise I18nError(Keys.AUTH_REGISTRATION_DISABLED, http_status=403)

    # 5. 决定 role + 哈希 + 创建
    role = "admin" if count == 0 else "user"
    pwd_hash = await hash_password_async(password)
    # user_repo.create 内部 .lower()（防 MySQL collation 撞库）+ 写 password_changed_at
    # 用户名唯一性：抛 IntegrityError，路由层捕获转 409 AUTH_USERNAME_TAKEN
    user = await user_repo.create(db, username=username, password_hash=pwd_hash, role=role)

    return CurrentUser(user_id=user.id, username=user.username, role=user.role)

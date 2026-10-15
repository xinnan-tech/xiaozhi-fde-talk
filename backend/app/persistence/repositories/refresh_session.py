"""refresh session（refresh_sessions 表）Repository。

token.py 只负责 JWT 签发 / 验签（无状态）；
「这个 jti 还活着吗 / 被谁用过 / 属于哪个用户」全部落在本表。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import RefreshSessionRecord

logger = logging.getLogger(__name__)

# 行状态机：active →（rotation）→ rotated →（grace 窗外再现）→ 视同泄露
#                          ↘（logout / reuse 击杀）→ revoked
STATUS_ACTIVE = "active"
STATUS_ROTATED = "rotated"
STATUS_REVOKED = "revoked"

# rotation 宽限窗：60s 窗内重放视为并发刷新（多 tab 撞车），窗外重放 = reuse。
ROTATION_GRACE_SECONDS = 60


def classify_refresh_session(
    row: Optional[RefreshSessionRecord],
    *,
    now: Optional[datetime] = None,
) -> str:
    """按行状态分类 refresh token：返回 "valid" / "revoked" / "reuse"。

    - 无行 → valid：迁移前签发的 legacy token（没有登记记录），按有效处理
      ——存量用户 cookie 里的 token 不能因为升级就被全量踢下线。
    - revoked → revoked。
    - rotated 且超过 grace 窗 → reuse（泄露信号）。
    - 其余（active，或 rotated 窗内）→ valid。
    - 未知 status → warning + valid 兜底（兼容语义同 legacy，不因状态漂移踢存量用户）。

    SQLite 读回 naive datetime，统一按 UTC 解释（同 pwd_changed_at
    处理——CI UTC 约定）。
    """
    if row is None:
        return "valid"
    if row.status == STATUS_REVOKED:
        return "revoked"
    if row.status not in (STATUS_ACTIVE, STATUS_ROTATED):
        # 未知 status：log + valid 兜底（兼容语义同 legacy 无行，不踢存量用户）。
        logger.warning(
            "refresh_sessions 未知 status=%r（jti=%s）——按 valid 兜底，疑似状态漂移",
            row.status, row.jti,
        )
        return "valid"
    if row.status == STATUS_ROTATED:
        rotated_at = row.rotated_at
        if rotated_at is not None:
            if rotated_at.tzinfo is None:
                rotated_at = rotated_at.replace(tzinfo=timezone.utc)
            now = now or datetime.now(timezone.utc)
            if (now - rotated_at).total_seconds() > ROTATION_GRACE_SECONDS:
                return "reuse"
    return "valid"


class RefreshSessionRepository:
    """refresh_sessions 表读写。调用方传 db（Depends(get_db)），
    方法内部自行 commit——auth 路径的会话登记与请求内其他事务无耦合。
    """

    async def get(
        self, db: AsyncSession, jti: str
    ) -> Optional[RefreshSessionRecord]:
        return await db.get(RefreshSessionRecord, jti)

    async def register(
        self, db: AsyncSession, *, jti: str, user_id: str, expires_at: datetime
    ) -> None:
        """login / register 签发 refresh token 时登记 active 行。"""
        db.add(RefreshSessionRecord(
            jti=jti, user_id=user_id, status=STATUS_ACTIVE, expires_at=expires_at,
        ))
        await self._purge_expired(db, user_id)
        await db.commit()

    async def rotate(
        self,
        db: AsyncSession,
        *,
        old_jti: str,
        old_row: Optional[RefreshSessionRecord],
        old_expires_at: datetime,
        user_id: str,
        new_jti: str,
        new_expires_at: datetime,
    ) -> None:
        """一次性使用（rotation）：旧 jti 转移出 active + 新行登记 active。

        - 无行（legacy 首见）：补登记 rotated，后续重放受 grace/reuse 约束。
        - active：条件 UPDATE 原子转移（PG/MySQL 无 BEGIN IMMEDIATE，读-改-写
          会被并发 logout / reuse 击杀 lost-update 覆盖 → 已撤销 session 复活）。
          rowcount=0 = 行被并发改写 → db.refresh 强制重读（绕过 identity
          map）：非 active/rotated 抛 ValueError（route 转 401），grace
          窗内则放行落新对。
        - rotated（grace 窗内重放）：不动旧行——锚点不重置，防持续重放无限续窗。
        """
        now = datetime.now(timezone.utc)
        if old_row is None:
            db.add(RefreshSessionRecord(
                jti=old_jti, user_id=user_id, status=STATUS_ROTATED,
                rotated_at=now, expires_at=old_expires_at,
            ))
        elif old_row.status == STATUS_ACTIVE:
            res = await db.execute(
                update(RefreshSessionRecord)
                .where(
                    RefreshSessionRecord.jti == old_jti,
                    RefreshSessionRecord.status == STATUS_ACTIVE,
                )
                .values(status=STATUS_ROTATED, rotated_at=now)
                .execution_options(synchronize_session=False)
            )
            if res.rowcount == 0:
                # rowcount=0 = 行被并发改写；db.refresh 绕过 identity map 拿 DB 当前值。
                try:
                    await db.refresh(old_row)
                except InvalidRequestError as e:
                    # 行被并发 purge 删除（双 tab + JWT leeway 末 30s：赢家
                    # rotate 顺手清了本行）——token 已死，转 401 不留 500。
                    raise ValueError(
                        f"rotate() 竞争失败: jti={old_jti} 行已被并发清除"
                    ) from e
                if old_row.status not in (STATUS_ACTIVE, STATUS_ROTATED):
                    raise ValueError(
                        f"rotate() 竞争失败: jti={old_jti} 行已被并发改写为 "
                        f"{old_row.status}，拒绝转移"
                    )
                # ROTATED = grace 窗内并发重放；ACTIVE = 并发写回滚：放行落新对。
        elif old_row.status != STATUS_ROTATED:
            # REVOKED / 未知 status：route 已按 verdict 分流，此为第二道防线。
            raise ValueError(
                f"rotate() on revoked session: jti={old_jti} 已撤销，禁止复活"
            )
        # rotated（grace 窗内重放）：不动旧行——锚点不重置，防持续重放无限续窗。
        db.add(RefreshSessionRecord(
            jti=new_jti, user_id=user_id, status=STATUS_ACTIVE,
            expires_at=new_expires_at,
        ))
        try:
            # purge + commit：autoflush 触发 INSERT，legacy 同 jti 并发首见撞 PK。
            await self._purge_expired(db, user_id)
            await db.commit()
        except IntegrityError as e:
            # → route 401；用户重试命中 T1 已登记行走 grace 路径。
            await db.rollback()
            raise ValueError(
                f"rotate() 并发补登记冲突: jti={old_jti} 已被并发首见登记"
            ) from e

    async def revoke_by_jti(
        self, db: AsyncSession, *, jti: str, user_id: str, expires_at: datetime
    ) -> None:
        """logout：按 jti 撤销。无行（legacy token）则补登记 revoked 行——
        保证迁移前签发的 token logout 后同样失效。幂等：已 revoked 保持。
        """
        row = await self.get(db, jti)
        if row is None:
            db.add(RefreshSessionRecord(
                jti=jti, user_id=user_id, status=STATUS_REVOKED,
                expires_at=expires_at,
            ))
        else:
            row.status = STATUS_REVOKED
        await db.commit()

    async def revoke_all_for_user(self, db: AsyncSession, user_id: str) -> int:
        """reuse 检测触发：撤销该用户全部 refresh session（全家击杀）。
        返回受影响行数，供告警日志记录。"""
        res = await db.execute(
            update(RefreshSessionRecord)
            .where(
                RefreshSessionRecord.user_id == user_id,
                RefreshSessionRecord.status != STATUS_REVOKED,
            )
            .values(status=STATUS_REVOKED)
            # 关闭 ORM 内存同步：避免 Python 侧 naive/aware tz 混比抛 TypeError。
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        return res.rowcount or 0

    async def _purge_expired(self, db: AsyncSession, user_id: str) -> None:
        """惰性清理（登记新行顺手删）;频率≈rotation,无需定时任务。"""
        await db.execute(
            delete(RefreshSessionRecord)
            .where(
                RefreshSessionRecord.user_id == user_id,
                RefreshSessionRecord.expires_at < datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )


# 全局默认实例（调用方自传 db）
refresh_session_repo = RefreshSessionRepository()

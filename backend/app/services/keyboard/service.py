"""键盘笔记服务。

覆盖式语义:每 session+user 唯一 1 行,POST 直接 UPSERT。复合 PK 物理保证唯一性,
无需应用层锁。`client_created_at` 保留「最初提交时刻」,`updated_at` 自动维护。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.domain.note import KeyboardNote
from app.persistence.db import SessionLocal
from app.persistence.models import SessionKeyboardText


async def upsert_keyboard_text(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    text: str,
    client_created_at: datetime,
) -> None:
    """PG 复合 PK 物理保证 UPSERT,不刷新 client_created_at。

    SQLite (开发环境) 不支持 `ON CONFLICT DO UPDATE` —— 走 select-then-insert/update
    fallback,跟 PG UPSERT 表达同一语义。SQLite 是 dev/test 环境,无并发;行级 UPSERT
    是 dev/test 的退化路径,生产 PG 用 pg_insert。

    方言从 db.bind 拿——settings 里没有 db_dialect 字段(URL backend_name 才是真相源)。
    """
    dialect = db.bind.dialect.name if db.bind else "sqlite"
    if dialect == "postgresql":
        stmt = pg_insert(SessionKeyboardText).values(
            session_id=session_id,
            user_id=user_id,
            text=text,
            client_created_at=client_created_at,
        ).on_conflict_do_update(
            index_elements=[
                SessionKeyboardText.session_id,
                SessionKeyboardText.user_id,
            ],
            # 不刷 client_created_at——保留「用户最初提交时刻」,updated_at 自动更新
            set_={"text": text, "updated_at": func.now()},
        )
        await db.execute(stmt)
        return
    # SQLite / MySQL fallback:select-then-update
    existing = await db.get(SessionKeyboardText, (session_id, user_id))
    if existing is None:
        db.add(SessionKeyboardText(
            session_id=session_id,
            user_id=user_id,
            text=text,
            client_created_at=client_created_at,
        ))
    else:
        existing.text = text
        # updated_at 由 onupdate 触发


async def upsert_keyboard_text_auto(
    *,
    session_id: str,
    user_id: str,
    text: str,
    client_created_at: datetime,
) -> None:
    """自动管理 session 的 upsert。HTTP handler 调用。"""
    async with SessionLocal() as db:
        await upsert_keyboard_text(
            db,
            session_id=session_id,
            user_id=user_id,
            text=text,
            client_created_at=client_created_at,
        )
        await db.commit()


async def get_keyboard_text_auto(
    *, session_id: str, user_id: str,
) -> Optional[KeyboardNote]:
    async with SessionLocal() as db:
        rec = await db.get(SessionKeyboardText, (session_id, user_id))
        if rec is None:
            return None
        return KeyboardNote(
            session_id=rec.session_id,
            user_id=rec.user_id,
            text=rec.text,
            client_created_at=rec.client_created_at,
            updated_at=rec.updated_at,
        )
"""报告 Repository。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import ReportRecord


class ReportRepository:
    """报告持久化。"""

    async def get_by_interview(self, db: AsyncSession, interview_id: str) -> Optional[ReportRecord]:
        res = await db.execute(
            select(ReportRecord).where(ReportRecord.interview_id == interview_id)
        )
        return res.scalar_one_or_none()

    async def get_by_interview_auto(self, interview_id: str) -> Optional[ReportRecord]:
        """自动管理 session（services 层用，不直接 import SessionLocal）。"""
        from app.persistence.db import SessionLocal

        async with SessionLocal() as db:
            return await self.get_by_interview(db, interview_id)

    async def upsert(
        self,
        db: AsyncSession,
        interview_id: str,
        content_md: str,
        status: str,
        transcript_signature: str = "",
    ) -> ReportRecord:
        """按 interview_id 写入或更新（interview_id 上有唯一索引）。

        用方言级 upsert 取代 get-then-insert：两次并发的首次生成会双读
        None、双 insert，后者 commit 撞唯一索引直接 500。
        """
        from sqlalchemy.dialects.mysql import insert as mysql_insert
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        now = datetime.now(timezone.utc)
        values = dict(
            id=str(uuid4()),
            interview_id=interview_id,
            content_md=content_md,
            status=status,
            transcript_signature=transcript_signature,
            created_at=now,
            updated_at=now,
        )
        dialect = db.bind.dialect.name if db.bind else "sqlite"
        if dialect == "mysql":
            stmt = mysql_insert(ReportRecord).values(**values).on_duplicate_key_update(
                content_md=content_md, status=status,
                transcript_signature=transcript_signature, updated_at=now,
            )
        elif dialect == "postgresql":
            stmt = pg_insert(ReportRecord).values(**values).on_conflict_do_update(
                index_elements=[ReportRecord.interview_id],
                set_={"content_md": content_md, "status": status,
                      "transcript_signature": transcript_signature,
                      "updated_at": now},
            )
        else:  # sqlite
            stmt = sqlite_insert(ReportRecord).values(**values).on_conflict_do_update(
                index_elements=[ReportRecord.interview_id],
                set_={"content_md": content_md, "status": status,
                      "transcript_signature": transcript_signature,
                      "updated_at": now},
            )
        await db.execute(stmt)
        await db.commit()
        return await self.get_by_interview(db, interview_id)

    async def upsert_auto(
        self, interview_id: str, content_md: str, status: str, transcript_signature: str = ""
    ) -> ReportRecord:
        from app.persistence.db import SessionLocal

        async with SessionLocal() as db:
            return await self.upsert(db, interview_id, content_md, status, transcript_signature)


report_repo = ReportRepository()

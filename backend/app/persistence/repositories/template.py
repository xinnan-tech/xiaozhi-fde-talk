"""访谈模板 Repository。

封装 TemplateRecord 的 CRUD 与引用计数；事务由调用方管理。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.template import Template
from app.persistence.models import InterviewRecord, TemplateRecord


def _to_record(tpl: Template, *, version: str | None = None) -> TemplateRecord:
    """pydantic → ORM 行。冗余展示列与 content 同源序列化，整存整取。"""
    return TemplateRecord(
        id=tpl.id,
        name=tpl.name,
        icon_url=tpl.icon_url,
        icon_alt=tpl.icon_alt,
        version=version if version is not None else tpl.version,
        content=tpl.model_dump(mode="json"),
    )


class TemplateRepository:

    async def list_all(self, db: AsyncSession) -> list[TemplateRecord]:
        res = await db.execute(select(TemplateRecord).order_by(TemplateRecord.id))
        return list(res.scalars())

    async def get(
        self, db: AsyncSession, template_id: str
    ) -> Optional[TemplateRecord]:
        return await db.get(TemplateRecord, template_id)

    async def insert(self, db: AsyncSession, tpl: Template) -> TemplateRecord:
        rec = _to_record(tpl)
        db.add(rec)
        await db.flush()
        return rec

    async def replace(
        self, db: AsyncSession, tpl: Template, *, version: str
    ) -> TemplateRecord:
        rec = await db.get(TemplateRecord, tpl.id)
        if rec is None:
            rec = _to_record(tpl, version=version)
            db.add(rec)
        else:
            rec.name = tpl.name
            rec.icon_url = tpl.icon_url
            rec.icon_alt = tpl.icon_alt
            rec.version = version
            rec.content = tpl.model_dump(mode="json")
        await db.flush()
        return rec

    async def delete(self, db: AsyncSession, template_id: str) -> bool:
        rec = await db.get(TemplateRecord, template_id)
        if rec is None:
            return False
        await db.delete(rec)
        await db.flush()
        return True

    async def count_interviews(self, db: AsyncSession, template_id: str) -> int:
        res = await db.execute(
            select(func.count()).select_from(InterviewRecord).where(
                InterviewRecord.template_id == template_id
            )
        )
        return int(res.scalar() or 0)

    async def count_interviews_grouped(
        self, db: AsyncSession
    ) -> dict[str, int]:
        """按 template_id 分组计数（admin 列表 referenced 标记用，一次查询）。"""
        res = await db.execute(
            select(InterviewRecord.template_id, func.count())
            .group_by(InterviewRecord.template_id)
        )
        return {tid: int(n) for tid, n in res.all()}


# 单例（无状态，安全共享）
template_repo = TemplateRepository()

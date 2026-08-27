"""· DateTime 列加 timezone=True（M-013）。

时间戳原为 naive DateTime，sweep_stale_sessions 等处被迫手动 tz juggle
（.astimezone(utc).replace(tzinfo=None)）。改 timezone=True 让 ORM 统一以 aware
datetime 暴露，减少 naive/aware 混用错算。强不变量：所有 DateTime 列均 tz-aware。
"""
from __future__ import annotations

from sqlalchemy import DateTime

from app.persistence.models import Base


def test_all_datetime_columns_have_timezone():
    offenders = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, DateTime) and not col.type.timezone:
                offenders.append(f"{table.name}.{col.key}")
    assert not offenders, f"DateTime 列缺 timezone=True：{offenders}"

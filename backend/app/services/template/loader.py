"""模板存储：DB 支撑的进程内缓存。

- 对外保留同步读接口 get_template / list_templates（签名与文件时代一致），
  coaching/engine、reports/generator、sessions/manager、routes 等消费点零改动。
- 启动 warm()：建表（幂等，覆盖 dev create_all / CI 无库 / prod alembic 三条
  路径）→ 空表种子 seed.SEED_TEMPLATES → 全量灌缓存。
- admin 写操作（create/update/delete）：校验 → 写 DB → 同步刷新缓存。
  单进程语义（与 ConfigStore 的进程内广播一致）；多 worker 部署时其他进程
  缓存不自动失效，需重启——当前部署模型为单进程，不为此引入跨进程机制。
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Optional

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.template import Template
from app.persistence.repositories.template import template_repo

logger = logging.getLogger(__name__)

_TEMPLATE_ID_RE = re.compile(r"^[a-z0-9-]+$")

# 进程内缓存：warm() 灌入；写操作同步刷新
_cache: dict[str, Template] = {}


def _bump_version(v: str) -> str:
    try:
        return str(int(v) + 1)
    except ValueError:
        return "1"


def _validate(tpl: Template) -> None:
    """业务校验（结构合法性由 pydantic 在路由层把关，这里管跨字段规则）。"""
    if not _TEMPLATE_ID_RE.match(tpl.id):
        raise I18nError(
            Keys.TEMPLATE_INVALID, http_status=422,
            field="id", reason="仅允许小写字母、数字、连字符（如 fde-research）",
        )
    keys = [f.key for f in tpl.session.base_fields]
    dup = sorted(k for k, c in Counter(keys).items() if c > 1)
    if dup:
        raise I18nError(
            Keys.TEMPLATE_INVALID, http_status=422,
            field="session.base_fields[].key",
            reason=f"重复字段：{'、'.join(dup)}",
        )
    ids = [m.id for m in tpl.coaching.must_ask]
    dup_ids = sorted(i for i, c in Counter(ids).items() if c > 1)
    if dup_ids:
        raise I18nError(
            Keys.TEMPLATE_INVALID, http_status=422,
            field="coaching.must_ask[].id",
            reason=f"重复 id：{'、'.join(dup_ids)}",
        )
    # goal / end_time 是保留字段：goal 不在 base_fields 里也能被 setup 引用；
    # end_time 是创建访谈时由时长算出的运行时字段（历史模板会引用）
    known = set(keys) | {"goal", "end_time"}
    for attr in ("extract_to", "required"):
        missing = sorted(
            k for k in getattr(tpl.session.setup, attr) if k not in known
        )
        if missing:
            raise I18nError(
                Keys.TEMPLATE_INVALID, http_status=422,
                field=f"session.setup.{attr}",
                reason=f"引用了未定义字段：{'、'.join(missing)}",
            )


async def warm() -> None:
    """启动期：建表（缺则补，幂等）→ 空表种子 → 全量灌缓存。"""
    from app.persistence.db import engine
    from app.persistence.models import TemplateRecord
    from app.services.template.seed import SEED_TEMPLATES

    async with engine.begin() as conn:
        await conn.run_sync(TemplateRecord.__table__.create, checkfirst=True)

    from app.persistence.db import SessionLocal
    async with SessionLocal() as db:
        rows = await template_repo.list_all(db)
        if not rows:
            for data in SEED_TEMPLATES:
                db.add(TemplateRecord(
                    id=data["id"], name=data["name"],
                    icon_url=data.get("icon_url", ""),
                    icon_alt=data.get("icon_alt", ""),
                    version=data.get("version", "1"),
                    content=data,
                ))
            await db.commit()
            logger.info("已种入 %d 个种子模板", len(SEED_TEMPLATES))
            rows = await template_repo.list_all(db)

    _cache.clear()
    for r in rows:
        try:
            _cache[r.id] = Template(**r.content)
        except Exception as e:  # noqa: BLE001
            logger.error("模板行损坏，跳过：%s %s", r.id, e)
    logger.info("模板缓存就绪：%d 个", len(_cache))


def get_template(template_id: str) -> Optional[Template]:
    """同步读缓存。miss 返回 None（不查 DB——运行时路径不允许阻塞）。"""
    return _cache.get(template_id)


def list_templates() -> list[Template]:
    return list(_cache.values())


def resolve_template(
    template_id: str, snapshot: Optional[dict],
) -> Optional[Template]:
    """快照优先（创建访谈时的模板），NULL/损坏回退当前缓存。"""
    if snapshot:
        try:
            return Template(**snapshot)
        except Exception as e:  # noqa: BLE001
            logger.warning("模板快照损坏，回退当前模板 %s：%s", template_id, e)
    return get_template(template_id)


async def create_template(tpl: Template) -> Template:
    _validate(tpl)
    from app.persistence.db import SessionLocal
    async with SessionLocal() as db:
        if await template_repo.get(db, tpl.id) is not None:
            raise I18nError(Keys.TEMPLATE_ID_TAKEN, http_status=409, id=tpl.id)
        await template_repo.insert(db, tpl)
        await db.commit()
    _cache[tpl.id] = tpl
    return tpl


async def update_template(tpl: Template) -> Template:
    """全量替换；version 由后端 +1（忽略请求里的 version，防并发错乱）。"""
    _validate(tpl)
    from app.persistence.db import SessionLocal
    async with SessionLocal() as db:
        rec = await template_repo.get(db, tpl.id)
        if rec is None:
            raise I18nError(Keys.HTTP_TEMPLATE_NOT_FOUND, http_status=404)
        new_version = _bump_version(rec.version)
        # 先构造后传递：content 与 version 冗余列必须同源自增值，
        # 否则重启 warm() 用 Template(**content) 重建缓存会带回旧 version
        updated = tpl.model_copy(update={"version": new_version})
        await template_repo.replace(db, updated, version=new_version)
        await db.commit()
    _cache[tpl.id] = updated
    return updated


async def delete_template(template_id: str) -> None:
    from app.persistence.db import SessionLocal
    async with SessionLocal() as db:
        if await template_repo.get(db, template_id) is None:
            raise I18nError(Keys.HTTP_TEMPLATE_NOT_FOUND, http_status=404)
        n = await template_repo.count_interviews(db, template_id)
        if n > 0:
            raise I18nError(
                Keys.TEMPLATE_REFERENCED, http_status=409,
                id=template_id, count=n,
            )
        await template_repo.delete(db, template_id)
        await db.commit()
    _cache.pop(template_id, None)


def _iso(dt) -> Optional[str]:
    """datetime → UTC ISO 8601（admin 列表用）。"""
    from datetime import timezone
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


async def admin_list() -> list[dict]:
    """admin 列表：冗余展示列 + referenced（是否被访谈引用，删除保护提示用）。"""
    from app.persistence.db import SessionLocal

    async with SessionLocal() as db:
        rows = await template_repo.list_all(db)
        counts = await template_repo.count_interviews_grouped(db)
    return [
        {
            "id": r.id, "name": r.name, "icon_url": r.icon_url,
            "icon_alt": r.icon_alt, "version": r.version,
            "updated_at": _iso(r.updated_at or r.created_at),
            "referenced": counts.get(r.id, 0) > 0,
        }
        for r in rows
    ]

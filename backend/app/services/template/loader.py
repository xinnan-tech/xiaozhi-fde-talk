"""模板存储：DB 支撑的进程内缓存。

读路径同步签名（get_template / list_templates）；写路径校验后落 DB + 刷缓存。
多 worker 部署下其他进程缓存不自动失效——当前单进程部署，不为此引入广播机制。
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
    """版本号 +1；非法字符串、负数、或 +1 后超 14 位都抛 422。

    14 位上限给 DB 列宽 String(16) 留 2 位余量；99 万亿次更新够用。
    失败抛错比静默回退到 "1" 安全——前者暴露问题，后者让乐观锁条件恒真、
    并发更新静默丢失（#1 旧实现的根因）。
    """
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise I18nError(
            Keys.TEMPLATE_INVALID, http_status=422,
            field="version", reason="版本号必须是数字字符串",
        ) from None
    if n < 1:
        raise I18nError(
            Keys.TEMPLATE_INVALID, http_status=422,
            field="version", reason="版本号必须 >= 1",
        )
    bumped = n + 1
    if len(str(bumped)) > 14:
        raise I18nError(
            Keys.TEMPLATE_INVALID, http_status=422,
            field="version", reason="版本号已接近上限，无法继续 +1",
        )
    return str(bumped)


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
    # 创建时强制 version=1：忽略客户端指定值，避免「先指定 16 位 version
    # 再 +1 触发 DB 列宽溢出」之类的边界（#2）；同时与 update 时由服务端 +1
    # 的策略对齐——版本号是服务端发牌的，客户端不能伪造
    if tpl.version != "1":
        tpl = tpl.model_copy(update={"version": "1"})
    from sqlalchemy.exc import IntegrityError
    from app.persistence.db import SessionLocal
    async with SessionLocal() as db:
        # 抢先判重给清晰错误；并发场景靠 IntegrityError 兜底（TOCTOU 竞争）
        if await template_repo.get(db, tpl.id) is not None:
            raise I18nError(Keys.TEMPLATE_ID_TAKEN, http_status=409, id=tpl.id)
        try:
            await template_repo.insert(db, tpl)
            await db.commit()
        except IntegrityError as e:
            await db.rollback()
            raise I18nError(
                Keys.TEMPLATE_ID_TAKEN, http_status=409, id=tpl.id,
            ) from e
    _cache[tpl.id] = tpl
    return tpl


async def update_template(tpl: Template) -> Template:
    """全量替换；期望版本由客户端提交，服务端 +1 后写回。

    乐观锁：UPDATE WHERE version = expected_version——影响 0 行说明另一写者
    已先于本请求提交，返回 409 让客户端重新加载再决定。客户端必须把上一次
    响应里的 version 写回本地副本再保存，否则 `expected_version = tpl.version`
    与刚读到的 DB 版本不匹配（条件恒假）会被 409 误伤。
    """
    from app.persistence.db import SessionLocal
    from app.persistence.repositories.template import _OptimisticLockError
    _validate(tpl)
    async with SessionLocal() as db:
        rec = await template_repo.get(db, tpl.id)
        if rec is None:
            raise I18nError(Keys.HTTP_TEMPLATE_NOT_FOUND, http_status=404)
        # 期望版本=客户端手里的版本号（=最近一次 GET/创建/更新响应的 version）。
        # 用 DB 刚读到的版本会让条件恒真，完全拦不住「人类打开编辑器改两分钟」
        # 这类真实场景（#1）；服务端只负责 +1，不背书客户端版本是否「最新」
        new_version = _bump_version(tpl.version)
        # 先构造后传递：content 与 version 冗余列必须同源自增值，
        # 否则重启 warm() 用 Template(**content) 重建缓存会带回旧 version
        updated = tpl.model_copy(update={"version": new_version})
        try:
            await template_repo.replace(
                db, updated, version=new_version,
                expected_version=tpl.version,
            )
            await db.commit()
        except _OptimisticLockError as e:
            await db.rollback()
            raise I18nError(
                Keys.TEMPLATE_VERSION_CONFLICT, http_status=409, id=tpl.id,
            ) from e
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

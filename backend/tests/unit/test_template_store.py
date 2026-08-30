"""模板存储：warm 种子、缓存读写、CRUD、业务校验、resolve_template。

走 _lifespan_app（dev DB，create_all 建表 + warm 已含在 lifespan 里）。
"""
from __future__ import annotations

import pytest

from app.domain.template import Template
from app.services.template import loader


@pytest.fixture(scope="module")
async def _lifespan_app():
    import os
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    os.environ.setdefault("APP_ENV", "dev")
    from app.app import create_app
    from app.core.config_store import get_config_store
    from app.core.settings import get_settings
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        yield app
    # lifespan 会把真实 dev DB 的 system_config 灌进进程级 ConfigStore 单例
    # （本机 dev 库 llm.output_language=en），泄漏到后续模块会让报告测试的
    # i18n pivot 误触发（mock 输出中文 vs 请求 en → 重试使 LLM 调用数翻倍）。
    # teardown 清空缓存，恢复「未 warm」的纯净基线（get_sync 回退 None）。
    get_config_store().invalidate()


def _tpl(tid: str = "store-t1", name: str = "存储测试") -> Template:
    return Template(
        id=tid, name=name, version="1",
        session={"goal": "", "base_fields": [
            {"key": "project", "label": "项目"},
        ], "setup": {"intro": "", "extract_to": ["project"], "required": ["project"]}},
        coaching={"playbook": "", "must_ask": [{"id": "q1", "text": "问"}]},
        report={"doc": ""},
    )


async def test_warm_seeds_pm(_lifespan_app):
    # lifespan 里 warm() 已跑：dev DB 若空表则种子 pm-research 必在
    assert loader.get_template("pm-research") is not None
    assert loader.get_template("pm-research").coaching.must_ask[0].id == "objective"


async def test_create_update_delete_cycle(_lifespan_app):
    await loader.create_template(_tpl())
    assert loader.get_template("store-t1").name == "存储测试"

    updated = await loader.update_template(_tpl(name="改名了"))
    assert updated.version == "2"                      # version 后端自动 +1
    assert loader.get_template("store-t1").name == "改名了"  # 缓存已刷新

    await loader.delete_template("store-t1")           # 无引用 → 可删
    assert loader.get_template("store-t1") is None


async def test_update_persists_bumped_version_in_content(_lifespan_app):
    # 回归：content 与 version 冗余列必须同源自增值——否则重启 warm()
    # 用 Template(**content) 重建缓存会带回旧 version，与列值自相矛盾
    from app.persistence.db import SessionLocal
    from app.persistence.models import TemplateRecord

    await loader.create_template(_tpl(tid="store-ver"))
    updated = await loader.update_template(_tpl(tid="store-ver", name="再改"))
    assert updated.version == "2"
    async with SessionLocal() as db:
        rec = await db.get(TemplateRecord, "store-ver")
        assert rec.version == "2"
        assert rec.content["version"] == "2"
    assert loader.get_template("store-ver").version == "2"
    await loader.delete_template("store-ver")


async def test_create_duplicate_id_409(_lifespan_app):
    from app.core.i18n import Keys
    from app.core.i18n.errors import I18nError

    await loader.create_template(_tpl(tid="store-dup"))
    with pytest.raises(I18nError) as ei:
        await loader.create_template(_tpl(tid="store-dup"))
    assert ei.value.code == Keys.TEMPLATE_ID_TAKEN
    await loader.delete_template("store-dup")


async def test_delete_referenced_409(_lifespan_app):
    from app.core.i18n import Keys
    from app.core.i18n.errors import I18nError
    from app.persistence.db import SessionLocal
    from app.persistence.models import InterviewRecord

    await loader.create_template(_tpl(tid="store-ref"))
    async with SessionLocal() as db:
        db.add(InterviewRecord(
            id="store-ref-i1", template_id="store-ref", status="created",
        ))
        await db.commit()
    try:
        with pytest.raises(I18nError) as ei:
            await loader.delete_template("store-ref")
        assert ei.value.code == Keys.TEMPLATE_REFERENCED
    finally:
        async with SessionLocal() as db:
            rec = await db.get(InterviewRecord, "store-ref-i1")
            await db.delete(rec)
            await db.commit()
        await loader.delete_template("store-ref")


async def test_validate_rules(_lifespan_app):
    from app.core.i18n import Keys
    from app.core.i18n.errors import I18nError

    # 1) id 格式
    bad = _tpl(tid="Bad_Id!")
    with pytest.raises(I18nError) as ei:
        await loader.create_template(bad)
    assert ei.value.code == Keys.TEMPLATE_INVALID
    assert ei.value.params["field"] == "id"

    # 2) base_fields key 重复
    dup = _tpl()
    dup.session.base_fields.append(dup.session.base_fields[0].model_copy())
    with pytest.raises(I18nError) as ei:
        await loader.create_template(dup)
    assert "重复" in ei.value.params["reason"]

    # 3) extract_to 引用不存在的字段
    ghost = _tpl()
    ghost.session.setup.extract_to = ["nope"]
    with pytest.raises(I18nError) as ei:
        await loader.create_template(ghost)
    assert ei.value.params["field"] == "session.setup.extract_to"


async def test_resolve_template_snapshot_priority(_lifespan_app):
    # 快照优先：即使当前模板已改/已删，快照原样返回
    snap = _tpl(tid="pm-research", name="旧版名称").model_dump(mode="json")
    resolved = loader.resolve_template("pm-research", snap)
    assert resolved.name == "旧版名称"
    # NULL/损坏快照回退当前模板
    assert loader.resolve_template("pm-research", None).name == "产品经理"
    assert loader.resolve_template("pm-research", {"broken": 1}).name == "产品经理"


async def test_admin_list_shape(_lifespan_app):
    items = await loader.admin_list()
    pm = [i for i in items if i["id"] == "pm-research"]
    assert len(pm) == 1
    assert set(pm[0].keys()) == {
        "id", "name", "icon_url", "icon_alt", "version", "updated_at", "referenced",
    }

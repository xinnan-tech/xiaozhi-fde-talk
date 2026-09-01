"""manager.update 的 TOCTOU 字节上限兜底校验。

回归 #167 round 2：openrz 第二轮评审指出 route 层
`_validate_base_info_size({**state.session.base_info, **req.base_info})` 与
`manager.update` 内部的 `self.get` + 合并 + `save_state_auto` 不在同一临界区
——并发 PATCH 串行 commit 时会让 base_info 累计越过 BASE_INFO_TOTAL_MAX_BYTES。

修复：manager.update 内对「本函数 GET 的最新快照 + PATCH 增量」merged 再跑一次
字节上限校验。即便 route 层基于过期快照放行，本函数内的最新 GET + merged 校验
仍然能挡下放大器；save_state 落库时 merged 必然 ≤ BASE_INFO_TOTAL_MAX_BYTES。
"""
from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.persistence.models import Base
from app.persistence.repositories.interview import interview_repo
from app.services.sessions.manager import manager
from app.transport.http.schemas import BASE_INFO_TOTAL_MAX_BYTES


@pytest.fixture
def mem_db(monkeypatch):
    """进程内 SQLite 内存库，monkeypatch 替换 SessionLocal。

    与 test_first_batch_flag.mem_db 同款：create_all 后所有会话都落这张库，
    各测试隔离，session 结束自动释放。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.persistence.db.SessionLocal", factory)
    monkeypatch.setattr("app.core.config_store.SessionLocal", factory)
    return engine, factory


async def _bootstrap(engine, factory, base_info: dict):
    """建表 + 创建一个 session（含给定 base_info）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    state = await manager.create("u-1", "pm-research", base_info, "目标")
    return state


def _bytes(base_info: dict) -> int:
    """按 base_info 在 DB 实际存储格式（json.dumps ensure_ascii=False）算字节。

    与 _validate_base_info_size.total 口径一致：含 key、{}、,、引号等结构开销。
    """
    return len(json.dumps(base_info, ensure_ascii=False, default=str).encode("utf-8"))


def _patch_payload(i: int) -> dict:
    """单次 PATCH 的增量 ≈ 1KB（10 字段、每字段 100 字节、key ≈ 9 字节）。"""
    return {f"add_{i:02d}_{j:02d}": "y" * 100 for j in range(10)}


@pytest.mark.asyncio
async def test_sequential_patches_total_size_limit_enforced_in_manager_update(mem_db):
    """连续 PATCH 直到 merged 超 64KB → manager.update 必须拒后续 PATCH。

    模拟 #167 round 2 攻击场景：初始 base_info（≤ 64KB），后续 N 次 PATCH 串行
    commit，每条 +1KB 增量。最后一次 PATCH 会让 merged > BASE_INFO_TOTAL_MAX_BYTES，
    必须被 manager.update 内的兜底校验拒。

    修复前：route 层校验基于自身 GET 快照，PATCH 都过；manager.update 内部不再校验，
    最终 DB 落 merged > 64KB 越过整体上限。
    修复后：manager.update 内部基于本函数 GET 的最新快照再校验 merged，超限 PATCH
    必抛 SESSION_BASE_INFO_TOTAL_TOO_LARGE（422）。
    """
    engine, factory = mem_db
    # 525 字段 × ~115B/字段 ≈ 60KB。每个字段 = 9B key + 100B value + 6B 结构。
    initial = {f"init_{i:04d}": "x" * 100 for i in range(525)}
    state = await _bootstrap(engine, factory, initial)

    initial_bytes = _bytes(state.session.base_info)
    patch_bytes = _bytes(_patch_payload(0))
    # 至少要发 8 次（60KB + 8×1.15KB ≈ 69KB），保险起见发 12 次。
    n_patches = 12

    failures: list[tuple[int, str]] = []
    for i in range(n_patches):
        try:
            await manager.update(state.session.id, _patch_payload(i), None)
        except I18nError as e:
            failures.append((i, e.code))

    final = await interview_repo.get_state_auto(state.session.id)
    final_bytes = _bytes(final.session.base_info)

    # 核心断言：DB 最终字节 ≤ 上限
    assert final_bytes <= BASE_INFO_TOTAL_MAX_BYTES, (
        f"manager.update 未兜底校验，base_info 越过 64KB：{final_bytes} > "
        f"{BASE_INFO_TOTAL_MAX_BYTES}"
    )
    # 至少一个 PATCH 因超限失败
    assert failures, f"{n_patches} 次连续 PATCH 应至少有一次因 merged > 64KB 被拒"
    for idx, code in failures:
        assert code == Keys.SESSION_BASE_INFO_TOTAL_TOO_LARGE, (
            f"PATCH #{idx} 失败但 code 错：{code}"
        )


@pytest.mark.asyncio
async def test_concurrent_patches_total_size_limit_enforced_in_manager_update(mem_db):
    """N=5 并发 PATCH 同一 session，最终 DB 字节必须 ≤ BASE_INFO_TOTAL_MAX_BYTES。

    回归点：并发场景下 route 层 GET 与 manager.update GET 之间可能有其他 PATCH
    先 commit；manager.update 内基于自身最新 GET 的 merged 校验是最终防线。

    本断言：DB 最终字节 ≤ 64KB。即便并发 PATCH 因 lost-update 没把全部 5KB 都
    落库（部分 PATCH 的 GET 抢在前面 commit 之前），也不会越过上限。
    """
    engine, factory = mem_db
    initial = {f"init_{i:04d}": "x" * 100 for i in range(525)}
    state = await _bootstrap(engine, factory, initial)
    # 留 5KB 余量，5 × ~1KB 增量足以触发上限
    n_patches = 5

    async def _patch(i: int) -> str:
        try:
            await manager.update(state.session.id, _patch_payload(i), None)
            return "ok"
        except I18nError:
            return "rejected"

    results = await asyncio.gather(*[_patch(i) for i in range(n_patches)])

    final = await interview_repo.get_state_auto(state.session.id)
    final_bytes = _bytes(final.session.base_info)

    # 核心断言：DB 最终字节 ≤ 上限（兜底校验生效）
    assert final_bytes <= BASE_INFO_TOTAL_MAX_BYTES, (
        f"并发 PATCH 后 base_info 越过 64KB：{final_bytes} > "
        f"{BASE_INFO_TOTAL_MAX_BYTES}，results={results}"
    )


@pytest.mark.asyncio
async def test_single_patch_near_limit_then_one_more_rejected(mem_db):
    """贴边测：动态算 PATCH 次数，先把 merged 推到 ≤ 64KB（应过），再 +1KB 必拒。

    比前两个测试更精确：基线 base_info 初始字节用 _bytes() 实测，然后循环发
    PATCH 直到 merged 越过 BASE_INFO_TOTAL_MAX_BYTES 前一次停下；最后再发
    一次 PATCH 必须被拒。验证 manager.update 内 merged 校验对 merged 超限
    触发精准。
    """
    engine, factory = mem_db
    initial = {f"k{i:04d}": "x" * 100 for i in range(525)}
    state = await _bootstrap(engine, factory, initial)
    initial_bytes = _bytes(state.session.base_info)
    assert initial_bytes <= BASE_INFO_TOTAL_MAX_BYTES  # 初始合法

    patch_bytes = _bytes(_patch_payload(0))
    # 算要发几次能贴边 ≤ 64KB；最后再发一次必拒
    remaining = BASE_INFO_TOTAL_MAX_BYTES - initial_bytes
    n_to_floor = max(0, remaining // patch_bytes)  # 这一发仍 OK（merged 刚好 ≤ 上限）
    for i in range(n_to_floor):
        await manager.update(state.session.id, _patch_payload(i), None)

    # 第 N+1 次 PATCH：merged > 64KB，必拒
    with pytest.raises(I18nError) as ei:
        await manager.update(state.session.id, _patch_payload(n_to_floor), None)
    assert ei.value.code == Keys.SESSION_BASE_INFO_TOTAL_TOO_LARGE
    assert ei.value.http_status == 422

    # DB 最终字节 ≤ 上限
    final = await interview_repo.get_state_auto(state.session.id)
    final_bytes = _bytes(final.session.base_info)
    assert final_bytes <= BASE_INFO_TOTAL_MAX_BYTES
"""JWT 密钥原子写入：_save_to_db 必须走 INSERT ... ON CONFLICT DO NOTHING。

回归守卫：不再使用 select-then-merge（TOCTOU）；多个 worker 并发首次写入时，
ON CONFLICT DO NOTHING 保证只有一行落地，其余 worker 的 INSERT 被忽略，
resolve() 随后重读得到赢家写入的密钥。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.core.secret import JWTSecretResolver


async def test_save_uses_on_conflict_do_nothing():
    """_save_to_db 用 INSERT OR IGNORE / ON CONFLICT，不靠先 select 判重。"""
    settings = MagicMock()
    settings.jwt_secret = None
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    sf = lambda: session  # noqa: E731
    r = JWTSecretResolver(settings, sf)
    await r._save_to_db("s3cret-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    sql = str(session.execute.call_args.args[0])
    assert "insert" in sql.lower() and (
        "conflict" in sql.lower() or "ignore" in sql.lower()
    )

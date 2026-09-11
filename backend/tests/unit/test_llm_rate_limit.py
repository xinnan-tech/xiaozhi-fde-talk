"""issue #240：LLM 转发路由 user_id 限流回归。

extract / first-batch / ocr 三个路由共用一份 _llm_user_limiter
（capacity=20、refill_per_hour=20）：单用户额度打通算更省成本——绕开
「分桶稀释成 60/h」的绕过路径。Depends(get_current_user) 先验 token，
没登录的用户在被 401 挡掉前不会消耗桶；已登录用户配额耗尽 → 429。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.i18n.errors import I18nError
from app.transport.http.routes import interviews as interviews_route


@pytest.fixture(autouse=True)
def _reset_llm_limiter():
    """模块级 RateLimiter 跨用例持续累加；用例前后清空。"""
    interviews_route._llm_user_limiter._buckets.clear()
    yield
    interviews_route._llm_user_limiter._buckets.clear()


def _user(uid: str = "llm-rl-user-1") -> SimpleNamespace:
    # 用独有前缀避免跟 test_rest_first_batch 的 "u-1" 等业务测试共用同一桶——
    # _llm_user_limiter 是模块级单例，跨文件共用；同名 user_id 会被其它测试污染。
    return SimpleNamespace(user_id=uid, username=uid, role="user")


async def test_extract_allows_burst_then_returns_429():
    """capacity=20：前 20 次放行（失败路径也消耗令牌），第 21 次 429。"""
    rl = interviews_route._llm_user_limiter
    user = _user()
    req = MagicMock()
    req.transcript = ""  # 空文本走 200 返回，不真调 LLM

    for _ in range(rl.capacity):
        resp = await interviews_route.extract_fields(req, user)
        assert resp.values == {}, "空文本路径返回空字典，不应撞限流"

    with pytest.raises(I18nError) as ei:
        await interviews_route.extract_fields(req, user)
    assert ei.value.http_status == 429


async def test_first_batch_allows_burst_then_returns_429(monkeypatch):
    """first-batch：直接看前 20 次走到 manager.get，21 次被限流挡。"""
    rl = interviews_route._llm_user_limiter
    user = _user()

    sessions_called = []

    async def fake_get(sid):
        sessions_called.append(sid)
        return None  # 404 路径在 manager.get 之后，不撞限流

    monkeypatch.setattr(interviews_route.manager, "get", fake_get)
    for _ in range(rl.capacity):
        with pytest.raises(I18nError) as ei:
            await interviews_route.first_batch_interview("s1", user)
        assert ei.value.http_status == 404
    with pytest.raises(I18nError) as ei:
        await interviews_route.first_batch_interview("s1", user)
    assert ei.value.http_status == 429
    assert len(sessions_called) == rl.capacity, "限流挡后不再访问 manager"


async def test_ocr_allows_burst_then_returns_429():
    """ocr：空 base64 → 422；连续 20 次空 base64 后第 21 次 429。"""
    rl = interviews_route._llm_user_limiter
    user = _user()

    class _OCRReq:
        image_base64 = "!!!!"  # 非合法 base64 → b64decode 抛 → 422

    for _ in range(rl.capacity):
        with pytest.raises(I18nError) as ei:
            await interviews_route.recognize_image(_OCRReq(), user)
        assert ei.value.http_status == 422

    with pytest.raises(I18nError) as ei:
        await interviews_route.recognize_image(_OCRReq(), user)
    assert ei.value.http_status == 429


async def test_three_routes_share_one_user_bucket():
    """extract / first-batch / ocr 共享同一份 _llm_user_limiter 桶。

    用户拿 extract 打满 20/h，再打 first-batch 应立即 429——不是新桶 20+1=41。
    这是关键：不共享桶就会被三路由分桶稀释到 60/h，堵不住烧钱。
    """
    rl = interviews_route._llm_user_limiter
    user = _user()

    # extract 打满
    req = MagicMock()
    req.transcript = ""
    for _ in range(rl.capacity):
        await interviews_route.extract_fields(req, user)

    # first-batch 接着打：应立即 429（共享桶已空）
    with pytest.raises(I18nError) as ei:
        await interviews_route.first_batch_interview("s1", user)
    assert ei.value.http_status == 429, (
        f"三路由必须共享桶，first-batch 不该拿到新 20 配额；实得 {ei.value.http_status}"
    )

    # ocr 同样应立即 429
    class _OCRReq:
        image_base64 = "!!!!"
    with pytest.raises(I18nError) as ei:
        await interviews_route.recognize_image(_OCRReq(), user)
    assert ei.value.http_status == 429


async def test_different_users_have_separate_buckets():
    """user_id 不同则桶各自独立：u1 打满后 u2 仍可继续。"""
    rl = interviews_route._llm_user_limiter
    u1 = _user("llm-rl-user-2a")
    u2 = _user("llm-rl-user-2b")
    req = MagicMock()
    req.transcript = ""

    for _ in range(rl.capacity):
        await interviews_route.extract_fields(req, u1)
    with pytest.raises(I18nError) as ei:
        await interviews_route.extract_fields(req, u1)
    assert ei.value.http_status == 429

    # u2 全新桶：放行
    resp = await interviews_route.extract_fields(req, u2)
    assert resp.values == {}

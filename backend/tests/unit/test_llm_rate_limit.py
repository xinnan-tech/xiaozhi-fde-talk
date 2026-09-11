"""issue #240：LLM 转发路由 user_id 限流回归。

extract / first-batch / ocr 三个路由共用一份 _llm_user_limiter
（capacity=20、refill_per_hour=20）：单用户额度打通算更省成本——绕开
「分桶稀释成 60/h」的绕过路径。Depends(get_current_user) 先验 token，
没登录的用户在被 401 挡掉前不会消耗桶；已登录用户配额耗尽 → 429。

round2 评审修复：限流挪到必要校验后、空返回路径前——空文本/坏图/已生成
会话等早返回不再消耗令牌；只有真正调 LLM/OCR 的请求才扣令牌。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.i18n.errors import I18nError
from app.transport.http.routes import interviews as interviews_route


@pytest.fixture(autouse=True)
def _reset_llm_limiter():
    """走 _reset_for_test 清桶：与 auth.py 五桶同款约定。

    直清 _buckets 跳过 env 守门——若 prod 误调测试 fixture 会把生产桶清空。
    走公开 reset 走 env 守门，prod 撞 env 守门空跑，更安全。
    """
    interviews_route._reset_for_test()
    yield
    interviews_route._reset_for_test()


def _user(uid: str = "llm-rl-user-1") -> SimpleNamespace:
    # 用独有前缀避免跟 test_rest_first_batch 的 "u-1" 等业务测试共用同一桶——
    # _llm_user_limiter 是模块级单例，跨文件共用；同名 user_id 会被其它测试污染。
    return SimpleNamespace(user_id=uid, username=uid, role="user")


def _tracker_limiter():
    """替换 _llm_user_limiter 为 capacity=20 的可计数限流器。

    P1.1 round2 后：早返回路径不调限流，调 LLM 路径才调。把计数器包成
    call_count 属性，让测试断言「该路径限流被调用 N 次」即可，不依赖真
    LLM adapter mock——避免测试跟 adapter 接口耦合。
    """
    rl = interviews_route._llm_user_limiter
    rl._buckets.clear()
    real_try_acquire = rl.try_acquire
    call_count = 0

    def counting_try_acquire(key):
        nonlocal call_count
        call_count += 1
        return real_try_acquire(key)

    rl.try_acquire = counting_try_acquire
    return rl, lambda: call_count


# ---- P1.1 round2：早返回路径不消耗令牌 ----


async def test_extract_empty_transcript_does_not_consume_token():
    """空文本走早返回 → 限流不被调用。

    表单自动保存循环、前端空串探测：req.transcript="" → 直接返空字典，不调
    LLM，不该扣令牌。
    """
    rl, get_calls = _tracker_limiter()
    user = _user()
    req = MagicMock()
    req.transcript = ""
    req.fields = ["a"]
    req.field_labels = {"a": "A"}
    req.field_types = {"a": "text"}
    req.current_values = {}

    for _ in range(rl.capacity * 3):
        resp = await interviews_route.extract_fields(req, user)
        assert resp.values == {"a": ""}, "空文本路径返回空字典"

    assert get_calls() == 0, (
        f"空文本早返回不应调限流；实际调用 {get_calls()} 次"
    )


async def test_ocr_bad_base64_does_not_consume_token():
    """坏图（b64decode 失败）走 422 → 限流不被调用。

    前端 OCR 按钮偶发重复触发、或图传一半失败重传：图坏就早返回 422，
    不该扣令牌。
    """
    _rl, get_calls = _tracker_limiter()
    user = _user()

    class _OCRReq:
        image_base64 = "!!!!"

    for _ in range(3):
        with pytest.raises(I18nError) as ei:
            await interviews_route.recognize_image(_OCRReq(), user)
        assert ei.value.http_status == 422

    assert get_calls() == 0, (
        f"坏图早返回不应调限流；实际调用 {get_calls()} 次"
    )


async def test_first_batch_not_found_does_not_consume_token(monkeypatch):
    """找不到会话 → 404 → 限流不被调用。

    客户端拿旧 session_id 反复重试：manager.get 返 None → 早返回 404，
    不该扣令牌。
    """
    _rl, get_calls = _tracker_limiter()
    user = _user()

    sessions_called = []

    async def fake_get(sid):
        sessions_called.append(sid)
        return None

    monkeypatch.setattr(interviews_route.manager, "get", fake_get)
    for _ in range(3):
        with pytest.raises(I18nError) as ei:
            await interviews_route.first_batch_interview("s1", user)
        assert ei.value.http_status == 404
    assert get_calls() == 0, (
        f"404 早返回不应调限流；实际调用 {get_calls()} 次"
    )


# ---- 调 LLM/OCR 路径消耗令牌，耗尽 429 ----


async def test_extract_429_after_capacity_consumed(monkeypatch):
    """走完 LLM 路径扣令牌；扣光后 429。

    用 tracker limiter：前 capacity 次真调用 try_acquire（都被 try_acquire
    内部令牌通过），第 capacity+1 次因桶空返 False → 429。LLM adapter
    mock 返固定 JSON，避免 qwen-plus 未配置下抛 LLM_NOT_CONFIGURED。
    """
    rl, get_calls = _tracker_limiter()
    user = _user()
    req = MagicMock()
    req.transcript = "非空文本"
    req.fields = ["a"]
    req.field_labels = {"a": "A"}
    req.field_types = {"a": "text"}
    req.current_values = {}

    # mock LLM adapter：让 chat_json 返固定 JSON，避免网络调用
    async def fake_chat_json(*args, **kwargs):
        return {"a": "extracted-value"}

    fake_llm = MagicMock()
    fake_llm.chat_json = AsyncMock(side_effect=fake_chat_json)
    monkeypatch.setattr("app.adapters.llm.factory.get_llm", lambda: fake_llm)
    # mock config_store：output_language 默认 zh_cn
    fake_store = MagicMock()
    fake_store.get = AsyncMock(return_value="zh_cn")
    monkeypatch.setattr("app.core.config_store.get_config_store", lambda: fake_store)

    for _ in range(rl.capacity):
        resp = await interviews_route.extract_fields(req, user)
        assert resp.values == {"a": "extracted-value"}
    assert get_calls() == rl.capacity

    with pytest.raises(I18nError) as ei:
        await interviews_route.extract_fields(req, user)
    assert ei.value.http_status == 429
    assert get_calls() == rl.capacity + 1


async def test_three_routes_share_one_user_bucket(monkeypatch):
    """extract / first-batch / ocr 共享同一份 _llm_user_limiter 桶。

    用户拿 extract 打满 20/h，再打 first-batch 应立即 429——不是新桶 20+1=41。
    这是关键：不共享桶就会被三路由分桶稀释到 60/h，堵不住烧钱。
    """
    rl, get_calls = _tracker_limiter()
    user = _user()

    # extract 打满
    req = MagicMock()
    req.transcript = "非空"
    req.fields = ["a"]
    req.field_labels = {"a": "A"}
    req.field_types = {"a": "text"}
    req.current_values = {}
    fake_llm = MagicMock()
    fake_llm.chat_json = AsyncMock(return_value={"a": "x"})
    monkeypatch.setattr("app.adapters.llm.factory.get_llm", lambda: fake_llm)
    fake_store = MagicMock()
    fake_store.get = AsyncMock(return_value="zh_cn")
    monkeypatch.setattr("app.core.config_store.get_config_store", lambda: fake_store)
    for _ in range(rl.capacity):
        await interviews_route.extract_fields(req, user)
    assert get_calls() == rl.capacity

    # first-batch 接着打：mock 真实 state 让限流路径被执行（不走 404 / 已结束早返回）
    async def fake_get(sid):
        return SimpleNamespace(
            session=SimpleNamespace(
                user_id=user.user_id,
                status="created",  # 直接字符串，避开 SimpleNamespace 不可哈希
                first_batch_generated=False,
            ),
            items=[],
        )

    fake_rt = MagicMock()
    fake_rt.engine.first_generate = AsyncMock()
    monkeypatch.setattr(interviews_route.manager, "get", fake_get)
    monkeypatch.setattr(interviews_route.registry, "get", lambda sid: fake_rt)
    with pytest.raises(I18nError) as ei:
        await interviews_route.first_batch_interview("s1", user)
    assert ei.value.http_status == 429, (
        f"三路由必须共享桶，first-batch 不该拿到新 20 配额；实得 {ei.value.http_status}"
    )


async def test_different_users_have_separate_buckets(monkeypatch):
    """user_id 不同则桶各自独立：u1 打满后 u2 仍可继续。"""
    rl, get_calls = _tracker_limiter()
    u1 = _user("llm-rl-user-2a")
    u2 = _user("llm-rl-user-2b")
    req = MagicMock()
    req.transcript = "非空"
    req.fields = ["a"]
    req.field_labels = {"a": "A"}
    req.field_types = {"a": "text"}
    req.current_values = {}
    fake_llm = MagicMock()
    fake_llm.chat_json = AsyncMock(return_value={"a": "x"})
    monkeypatch.setattr("app.adapters.llm.factory.get_llm", lambda: fake_llm)
    fake_store = MagicMock()
    fake_store.get = AsyncMock(return_value="zh_cn")
    monkeypatch.setattr("app.core.config_store.get_config_store", lambda: fake_store)

    for _ in range(rl.capacity):
        await interviews_route.extract_fields(req, u1)
    with pytest.raises(I18nError) as ei:
        await interviews_route.extract_fields(req, u1)
    assert ei.value.http_status == 429

    # u2 全新桶：放行
    resp = await interviews_route.extract_fields(req, u2)
    assert resp.values == {"a": "x"}

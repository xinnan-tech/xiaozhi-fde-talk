"""AI 一句话生成模板：LLM 输出规整（_normalize/_extract_json）+ 端点行为。

不请求真实 LLM——端点测试 monkeypatch generator.get_llm 换桩，
规整逻辑直接喂「故意弄脏」的 LLM 输出验证各清洗分支。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.i18n.errors import I18nError
from app.persistence.db import SessionLocal
from app.persistence.models import User
from app.services.template.generator import (
    _extract_json,
    _normalize,
    generate_template,
)
from app.services.auth.token import create_access_token


# 故意弄脏的 LLM 输出：围栏包裹、非法 id、字段 key 非法/重复、type 乱填、
# setup 引用未定义字段、must_ask 漏 id / 重复 id / 空文本 / priority 乱序
_DIRTY_OUTPUT = """好的，这是您要的模板：
```json
{
  "id": "CS Return!",
  "name": "客服回访",
  "session": {
    "name": "客户回访",
    "goal": "说明本次回访目的",
    "base_fields": [
      {"key": "Customer Name", "label": "客户", "type": "text", "required": true},
      {"key": "customer_name", "label": "客户姓名"},
      {"key": "visit_time", "label": "回访时间", "type": "datetime"},
      {"key": "talk_sec", "label": "通话时长", "type": "秒数"}
    ],
    "setup": {
      "intro": "一句话说清回访对象与目的",
      "extract_to": ["field_1", "goal", "ghost"],
      "required": ["visit_time", "ghost"]
    }
  },
  "coaching": {
    "playbook": "你是客服回访教练",
    "must_ask": [
      {"text": "本次联系是否顺畅", "priority": 99},
      {"id": "satisfaction", "text": "满意度打几分", "priority": 1},
      {"id": "satisfaction", "text": "重复 id 的一条"},
      {"text": "   "},
      {"id": "renew", "text": "续约意向如何", "desc": "关键决策问题"}
    ]
  },
  "report": {"doc": "# {{session.customer_name}} 回访报告\\n\\n## 小结"}
}
```"""


class _FakeLLM:
    """测试桩：configured 可控，chat_text 返回预置文本。"""

    def __init__(self, text: str = "", configured: bool = True) -> None:
        self._text = text
        self._configured = configured
        self.calls: list[dict] = []

    @property
    def configured(self) -> bool:
        return self._configured

    async def chat_text(self, system, user, retries=2,  # noqa: ANN001
                        json_mode=False, max_tokens=None) -> str:
        self.calls.append({"system": system, "user": user,
                           "json_mode": json_mode, "max_tokens": max_tokens})
        return self._text


# ---- _extract_json ----

@pytest.mark.asyncio
async def test_extract_json_takes_fence_block():
    data = _extract_json(_DIRTY_OUTPUT)
    assert data["name"] == "客服回访"


@pytest.mark.asyncio
async def test_extract_json_no_block_raises():
    with pytest.raises(I18nError) as e:
        _extract_json("抱歉，我无法完成这个任务。")
    assert e.value.code == "llm.no_json_block"


@pytest.mark.asyncio
async def test_extract_json_bad_json_raises():
    with pytest.raises(I18nError) as e:
        _extract_json('```json\n{"a": 1,}\n```')
    assert e.value.code == "llm.invalid_json"


@pytest.mark.asyncio
async def test_extract_json_handles_extra_braces_in_text():
    """LLM 输出夹杂解释文本（含 {...}）也能提取首个平衡 JSON 块，避免贪婪匹配。

    贪婪正则 `{.*}` 会从首 { 一路匹配到末 }，触发 json.loads 的 Extra data。
    """
    mixed = (
        '好的，我参考了 "{另一模板示例 id=t1}" 这条。\n'
        '正式输出：\n'
        '{"id": "x", "name": "n"}'
        '\n完。'
    )
    parsed = _extract_json(mixed)
    assert parsed == {"id": "x", "name": "n"}


@pytest.mark.asyncio
async def test_extract_json_unfenced_uses_balanced_scan():
    """无围栏时也走平衡花括号扫描，区别于贪婪正则。

    文本里嵌了多个 {...}，应选首个平衡且能 json.loads 成功的块；
    跳过前面非 JSON 形态的占位（如 `{a: 1}` 没引号 → 非 JSON）。
    """
    text = '前缀 {a: 1} 中间 {"k": "v"} 结尾'
    parsed = _extract_json(text)
    assert parsed == {"k": "v"}


# ---- _normalize：各清洗分支 ----

@pytest.mark.asyncio
async def test_normalize_dirty_output():
    tpl = _normalize(_extract_json(_DIRTY_OUTPUT))

    # 非法 id（大写/空格/感叹号）→ 置空，交给编辑器让用户定
    assert tpl.id == ""
    assert tpl.name == "客服回访"

    # 字段：非法 key 补占位、重复 key 去重、乱 type 落回 text
    keys = [f.key for f in tpl.session.base_fields]
    assert keys == ["field_1", "customer_name", "visit_time", "talk_sec"]
    assert [f.type for f in tpl.session.base_fields] == [
        "text", "text", "datetime", "text",
    ]

    # setup：只保留已定义 key（goal 是保留字段，ghost 被剔除）
    assert tpl.session.setup.extract_to == ["field_1", "goal"]
    assert tpl.session.setup.required == ["visit_time"]

    # must_ask：空文本剔除；漏 id 补 q{n}；重复 id 换新；priority 连续重排
    items = tpl.coaching.must_ask
    assert [i.id for i in items] == ["q1", "satisfaction", "q3", "renew"]
    assert [i.priority for i in items] == [1, 2, 3, 4]
    assert items[3].desc == "关键决策问题"


@pytest.mark.asyncio
async def test_normalize_minimal_output():
    """LLM 只给最简结构也能兜出合法 Template（默认值齐全）。"""
    tpl = _normalize({"id": "min-1", "name": "最简", "coaching": {
        "must_ask": [{"text": "唯一问题"}],
    }})
    assert tpl.id == "min-1"
    assert tpl.version == "1"
    assert tpl.icon_alt == "📋"
    assert tpl.coaching.must_ask[0].id == "q1"
    assert tpl.coaching.must_ask[0].priority == 1


async def test_normalize_preserves_end_time_in_setup_refs():
    """end_time 是运行时字段（loader._validate 允许），_normalize 不能误剥。

    回归：之前 _normalize 的 known set 不含 end_time，会把 LLM 引用了 end_time
    的 setup 项剔除，与 loader 校验口径不一致。
    """
    tpl = _normalize({
        "id": "with-end", "name": "带 end_time",
        "session": {
            "base_fields": [{"key": "start_time", "label": "开始时间"}],
            "setup": {"extract_to": ["start_time", "end_time"], "required": ["end_time"]},
        },
    })
    assert tpl.session.setup.extract_to == ["start_time", "end_time"]
    assert tpl.session.setup.required == ["end_time"]


async def test_normalize_safety_none_handled():
    """LLM 给 safety=null 时 normalize 兜成 []，不让 pydantic v2 拒成 502。"""
    tpl = _normalize({"id": "safety-null", "name": "null safety", "safety": None})
    assert tpl.safety == []


async def test_normalize_field_placeholder():
    """placeholder 是字符串则保留、非字符串丢弃；default 不由 LLM 决定（恒空）。"""
    tpl = _normalize({
        "id": "ph-1", "name": "占位",
        "session": {"base_fields": [
            {"key": "project", "label": "项目", "placeholder": "如：门店巡检系统"},
            {"key": "owner", "label": "负责人", "placeholder": 123},
        ]},
    })
    fields = {f.key: f for f in tpl.session.base_fields}
    assert fields["project"].placeholder == "如：门店巡检系统"
    assert fields["owner"].placeholder == ""
    assert all(f.default == "" for f in tpl.session.base_fields)


@pytest.mark.asyncio
async def test_generate_passes_max_tokens_and_prompt():
    fake = _FakeLLM(_DIRTY_OUTPUT)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.template.generator.get_llm", lambda: fake)
        tpl = await generate_template("客服回访模板")
    assert tpl.coaching.must_ask[0].id == "q1"
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["json_mode"] is True
    assert call["max_tokens"] == 4000  # 大输出：覆盖默认 1500 截断
    # user prompt 含参考样例（风格锚点）+ 用户需求
    assert "pm-research" in call["user"]
    assert "客服回访模板" in call["user"]


@pytest.mark.asyncio
async def test_generate_blank_brief_rejected():
    with pytest.raises(I18nError) as e:
        await generate_template("   ")
    assert e.value.code == "template.invalid"


@pytest.mark.asyncio
async def test_generate_llm_not_configured():
    fake = _FakeLLM(configured=False)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.template.generator.get_llm", lambda: fake)
        with pytest.raises(I18nError) as e:
            await generate_template("客服回访模板")
    assert e.value.code == "llm.not_configured"
    assert fake.calls == []  # fail fast：没拼 prompt 就拒了


# ---- 端点 ----

@pytest.fixture(scope="module")
async def _lifespan_app():
    import os
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    os.environ.setdefault("APP_ENV", "dev")
    from app.app import create_app
    from app.core.settings import get_settings
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


async def _admin_headers() -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    uid = f"gen-admin-{suffix}"
    ts = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        db.add(User(
            id=uid, username=f"gen_admin_{suffix}",
            password_hash="x", role="admin", password_changed_at=ts,
        ))
        await db.commit()
    token = await create_access_token(
        subject=uid, pwd_ver=int(ts.timestamp()), extra={"role": "admin"},
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_endpoint_requires_admin(_lifespan_app):
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/admin/templates/generate", json={"brief": "x"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_endpoint_returns_template_not_persisted(_lifespan_app, monkeypatch):
    fake = _FakeLLM(_DIRTY_OUTPUT)
    monkeypatch.setattr("app.services.template.generator.get_llm", lambda: fake)
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _admin_headers()
        r = await c.post("/api/v1/admin/templates/generate",
                         json={"brief": "做一个客服回访模板"}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == ""  # 非法 id 已被规整
        assert [i["priority"] for i in body["coaching"]["must_ask"]] == [1, 2, 3, 4]

        # 不落库：generate 不产生新模板
        listed = await c.get("/api/v1/admin/templates", headers=h)
        assert all(t["id"] != body["id"] or body["id"] == "" for t in listed.json())
        assert not any(t["name"] == "客服回访" for t in listed.json())


@pytest.mark.asyncio
async def test_endpoint_validates_body(_lifespan_app, monkeypatch):
    fake = _FakeLLM(_DIRTY_OUTPUT)
    monkeypatch.setattr("app.services.template.generator.get_llm", lambda: fake)
    transport = ASGITransport(app=_lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _admin_headers()

        # extra 字段注入 → 422（不透传给 LLM）
        r = await c.post("/api/v1/admin/templates/generate",
                         json={"brief": "x", "id": "hack"}, headers=h)
        assert r.status_code == 422

        # brief 超长 → 422
        r = await c.post("/api/v1/admin/templates/generate",
                         json={"brief": "长" * 2001}, headers=h)
        assert r.status_code == 422

        # 纯空白 → 服务层拒绝（pydantic min_length 只挡空串）
        r = await c.post("/api/v1/admin/templates/generate",
                         json={"brief": "   "}, headers=h)
        assert r.status_code == 422
        assert r.json()["code"] == "template.invalid"
        assert fake.calls == []

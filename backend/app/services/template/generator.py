"""AI 一句话生成访谈模板：brief → LLM → 规整后的 Template（不落库）。

落库仍走 POST /admin/templates（loader 校验是最终闸门）；这里负责把
LLM 自由输出规整成能进编辑器的形态：priority 编号、漏 id 补齐、引用了
未定义字段的 setup 项剔除、base_fields key / must_ask id 去重。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.adapters.llm.factory import get_llm
from app.core.i18n import Keys
from app.core.i18n.errors import I18nError
from app.domain.template import Template
from app.services.template.seed import SEED_TEMPLATES

# 整份模板 JSON（中文文案 + 报告骨架）实测约 1.5~2.5k token
_GEN_MAX_TOKENS = 4000

# brief 长度上限：太长没有额外收益，还拖慢生成
_BRIEF_MAX_CHARS = 2000

_ID_RE = re.compile(r"^[a-z0-9-]+$")

_SYSTEM_PROMPT = """你是访谈模板设计师，为语音访谈助手设计模板。用户会给一句话需求，\
你输出一份完整的访谈模板 JSON（全部文案用简体中文）。只输出 JSON，不要任何解释。

结构（字段缺省值可省略，但保持键名一致）：
{
  "id": "模板标识：英文小写+连字符，简短达意（如 pm-research、cs-return-visit）",
  "name": "模板显示名，2~6 个中文字（如 产品经理）",
  "session": {
    "name": "会话名称（如 用户/需求访谈）",
    "goal": "目标提示语：告诉访谈者这一栏该填什么",
    "base_fields": [
      {"key": "英文小写下划线", "label": "中文名", "type": "text|datetime|duration", "required": false, "placeholder": "文本字段的输入示例（可选，以\"如：\"开头）"}
    ],
    "setup": {
      "intro": "开场提示语：引导访谈者一句话描述本次访谈",
      "extract_to": ["要抽取的字段 key"],
      "required": ["必填的字段 key"]
    }
  },
  "coaching": {
    "playbook": "给 AI 教练的角色设定：一两句，说明访谈目的与辅导侧重",
    "must_ask": [
      {"id": "英文小写下划线，稳定不复用", "text": "必问的问题", "desc": "给访谈者的提示（可空）"}
    ]
  },
  "report": {
    "doc": "Markdown 报告骨架"
  }
}

硬性要求：
1. base_fields 3~6 个：通常含访谈对象/项目，时间类用 datetime、时长用 duration；\
文本字段的 placeholder 给行业通用示例（以"如："开头），不要输出 default。
2. must_ask 5~8 条：覆盖目标→痛点→现状→约束→决策→验收这条主线；不要输出 priority。
3. report.doc：`# 标题`（引用 {{session.字段key}}）+ 4~6 个 `## 小节`；用 {{session.字段key}} \
引用基础信息，用 {{ 中文占位说明 }} 标记由 AI 按访谈记录填写的部分。
4. setup.extract_to / required 只能引用 base_fields 里出现过的 key（可加 "goal"）。
5. 所有中文文案口语化、面向非专业用户。"""


def _extract_json(text: str) -> dict[str, Any]:
    """从 LLM 输出提取首个 JSON 对象（容忍 ```json 围栏 / 前后缀说明）。

    实现要点：
    1. 优先剥 ```json ... ``` 围栏（如果有），直接 json.loads——避免正则贪婪。
    2. 围栏不存在时，用平衡花括号扫描定位每个平衡 {...} 块，依次尝试解析
       直到首个成功为止；LLM 输出若夹多个 {...}（如"参考 {其它模板}"占位 +
       真 JSON）也能正确提取首个合法 JSON 块。
    """
    stripped = _strip_fence(text)
    candidates: list[str]
    if stripped is not None:
        candidates = [stripped]
    else:
        candidates = list(_balanced_objects(text)) or []
    if not candidates:
        raise I18nError(
            Keys.LLM_NO_JSON_BLOCK, http_status=502, snippet=text[:200]
        )
    last_err: json.JSONDecodeError | None = None
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except json.JSONDecodeError as e:
            last_err = e
            continue
        if not isinstance(parsed, dict):
            raise I18nError(
                Keys.LLM_INVALID_JSON, http_status=502,
                err="根节点不是对象", json_str=cand[:200],
            )
        return parsed
    # 走到这说明所有候选都解析失败
    raise I18nError(
        Keys.LLM_INVALID_JSON, http_status=502,
        err=str(last_err) if last_err else "无可解析 JSON 块",
        json_str=candidates[0][:200],
    )


def _strip_fence(text: str) -> str | None:
    """剥 ```json ... ``` 围栏（含首尾空白）；不存在返回 None。"""
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else None


def _balanced_objects(text: str):
    """生成器：依次产出每个平衡 {...} 块（不嵌字符串内），按出现顺序。"""
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, c in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start != -1:
                yield text[start:i + 1]
                start = -1


def _normalize(raw: dict[str, Any]) -> Template:
    """把 LLM 的自由输出规整成能进编辑器的 Template。"""
    data: dict[str, Any] = json.loads(json.dumps(raw))  # 深拷贝，不动原始数据
    data.setdefault("version", "1")
    data.setdefault("icon_url", "")
    data.setdefault("icon_alt", "📋")
    data.setdefault("name", "")

    # id：非法/缺失置空——编辑器让用户自己定（创建时 id 必填且不可改）
    if not isinstance(data.get("id"), str) or not _ID_RE.match(data["id"]):
        data["id"] = ""

    session = data.get("session") if isinstance(data.get("session"), dict) else {}
    fields: list[dict[str, Any]] = [
        f for f in (session.get("base_fields") or []) if isinstance(f, dict)
    ]
    # 去重字段 key（保留首个），key 非法（非英文小写下划线）的补占位
    seen_keys: set[str] = set()
    clean_fields: list[dict[str, Any]] = []
    for i, f in enumerate(fields):
        key = f.get("key") if isinstance(f.get("key"), str) else ""
        if not re.match(r"^[a-z][a-z0-9_]*$", key):
            key = f"field_{i + 1}"
        while key in seen_keys:
            key = f"{key}_{i + 1}"
        seen_keys.add(key)
        clean_fields.append({
            "key": key,
            "label": f.get("label") if isinstance(f.get("label"), str) else key,
            "type": f.get("type") if f.get("type") in ("text", "datetime", "duration") else "text",
            "required": bool(f.get("required")),
            # placeholder 保留（LLM 生成示例占位）；default 不取 LLM 的——
            # 默认值是业务决定，由管理员在编辑器里配，AI 生成假默认值会被直接提交
            "placeholder": f.get("placeholder") if isinstance(f.get("placeholder"), str) else "",
        })
    session["base_fields"] = clean_fields

    # setup：只能引用已定义字段（goal / end_time 是保留字段——end_time 是运行时算的）
    setup = session.get("setup") if isinstance(session.get("setup"), dict) else {}
    known = seen_keys | {"goal", "end_time"}
    for attr in ("extract_to", "required"):
        refs = [k for k in (setup.get(attr) or []) if isinstance(k, str)]
        setup[attr] = [k for k in refs if k in known]
    session["setup"] = setup
    data["session"] = session

    # must_ask：去重 id + 漏 id 补齐 + priority 按顺序（与编辑器保存口径一致）
    coaching = data.get("coaching") if isinstance(data.get("coaching"), dict) else {}
    items: list[dict[str, Any]] = [
        it for it in (coaching.get("must_ask") or []) if isinstance(it, dict)
    ]
    seen_ids: set[str] = set()
    clean_items: list[dict[str, Any]] = []
    for i, it in enumerate(items):
        text = it.get("text") if isinstance(it.get("text"), str) else ""
        if not text.strip():
            continue  # 没有问题内容的一条没有意义
        item_id = it.get("id") if isinstance(it.get("id"), str) else ""
        item_id = re.sub(r"[^a-z0-9_]", "", item_id.lower())
        if not item_id or item_id in seen_ids:
            n = len(clean_items) + 1
            while f"q{n}" in seen_ids:
                n += 1
            item_id = f"q{n}"
        seen_ids.add(item_id)
        clean_items.append({
            "id": item_id,
            "text": text.strip(),
            "priority": len(clean_items) + 1,
            "desc": it.get("desc") if isinstance(it.get("desc"), str) else "",
        })
    coaching["must_ask"] = clean_items
    data["coaching"] = coaching

    report = data.get("report") if isinstance(data.get("report"), dict) else {}
    report.setdefault("doc", "")
    data["report"] = report
    # safety 必须 list：setdefault 不会把 None 替换成 []，pydantic v2 对 None 拒 → 502
    data["safety"] = data.get("safety") or []

    try:
        return Template.model_validate(data)
    except Exception as e:  # noqa: BLE001
        raise I18nError(
            Keys.LLM_SCHEMA_MISMATCH, http_status=502,
            err=str(e), json_str=json.dumps(data, ensure_ascii=False)[:200],
        ) from e


async def generate_template(brief: str) -> Template:
    """一句话需求 → 模板（不落库）。LLM 未配置/超时等错误原样上抛给前端。"""
    brief = (brief or "").strip()
    if not brief:
        raise I18nError(Keys.TEMPLATE_INVALID, http_status=422,
                        field="brief", reason="需求描述不能为空")
    if len(brief) > _BRIEF_MAX_CHARS:
        raise I18nError(Keys.TEMPLATE_INVALID, http_status=422,
                        field="brief",
                        reason=f"需求描述过长（>{_BRIEF_MAX_CHARS} 字）")

    llm = get_llm()
    if not llm.configured:
        # 未配置就 fail fast，不拼 prompt（provider 请求路径也有同款守卫）
        raise I18nError(Keys.LLM_NOT_CONFIGURED, http_status=502)
    # 参考样例：给 LLM 一个「好模板长什么样」的锚点，显著稳住结构与文案风格
    example = json.dumps(SEED_TEMPLATES[0], ensure_ascii=False, indent=2)
    user_prompt = (
        f"参考样例（结构与风格锚点，不要照抄内容）：\n{example}\n\n"
        f"用户需求：\n{brief}"
    )
    text = await llm.chat_text(
        _SYSTEM_PROMPT, user_prompt, json_mode=True, max_tokens=_GEN_MAX_TOKENS
    )
    return _normalize(_extract_json(text))

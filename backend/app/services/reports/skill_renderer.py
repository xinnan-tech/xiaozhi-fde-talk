"""报告中的 `{{skill: ...}}` 标记替换。

MVP 支持严格 JSON inputs，例如：
`{{skill: echo, inputs: {"title": "补充", "content": "hello"}}}`
"""
from __future__ import annotations

import json
import logging

from app.services.skill.executor import invoke_skill

logger = logging.getLogger(__name__)


def _fallback(skill_id: str, reason: str) -> str:
    return f"> 本节待生成：skill `{skill_id}` 执行失败（{reason}）"


def _parse_inputs(raw: str | None) -> tuple[dict, str]:
    if not raw:
        return {}, ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return {}, f"inputs 不是合法 JSON：{e.msg}"
    if not isinstance(parsed, dict):
        return {}, "inputs 必须是 JSON object"
    return parsed, ""


def _scan_json_end(text: str, start: int) -> int:
    """返回 JSON object/array 结束后的下标；失败返回 -1。"""
    if start >= len(text) or text[start] not in "{[":
        return -1
    pairs = {"{": "}", "[": "]"}
    stack = [pairs[text[start]]]
    in_str = False
    escape = False
    i = start + 1
    while i < len(text):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch in pairs:
                stack.append(pairs[ch])
            elif stack and ch == stack[-1]:
                stack.pop()
                if not stack:
                    return i + 1
        i += 1
    return -1


def _find_markers(md: str) -> list[tuple[int, int, str, str | None]]:
    """扫描所有 `{{skill: ...}}` 标记。

    支持两种格式：
    1. `{{skill: <id>}}` — 无 inputs
    2. `{{skill: <id>, inputs: <json>}}` — 带 inputs

    两条路径：先按 `, inputs:` + JSON 边界扫（严格路径，覆盖带 inputs 的标准用法）；
    找不到时退到扫下一个 `}}`（容错路径，覆盖无 inputs 或 inputs 异常的 LLM 长描述）。
    """
    markers: list[tuple[int, int, str, str | None]] = []
    pos = 0
    prefix = "{{skill:"
    while True:
        start = md.find(prefix, pos)
        if start < 0:
            break
        i = start + len(prefix)
        while i < len(md) and md[i].isspace():
            i += 1
        content_start = i

        # 严格路径：尝试 `, inputs: <json>}}`
        hit = _try_parse_with_inputs(md, start, content_start)
        if hit is not None:
            end_idx, skill_id, raw_inputs = hit
            markers.append((start, end_idx, skill_id, raw_inputs))
            pos = end_idx
            continue

        # 容错路径：扫下一个 `}}`，整段当 skill_id
        end_close = md.find("}}", content_start)
        if end_close < 0:
            pos = start + len(prefix)
            continue
        content = md[content_start:end_close].strip()
        if content:
            skill_id = _split_id_only(content)
            markers.append((start, end_close + 2, skill_id, None))
        pos = end_close + 2
    return markers


def _try_parse_with_inputs(
    md: str, start: int, content_start: int
) -> tuple[int, str, str] | None:
    """严格路径：找 `, inputs: <json>` 并用 _scan_json_end 定位 JSON 末尾。

    仅当 `, inputs:` 出现在**最近一个 `}}` 之前**才认；否则跳过严格路径、走容错，
    否则会跨越 `}}` 吃掉后面的 marker（容错路径能识别 `}}` 早闭合的情形）。
    """
    sep = ", inputs:"
    sep_pos = md.find(sep, content_start)
    if sep_pos < 0:
        return None
    # 如果 }} 在 , inputs: 之前出现 → 本 marker 不带 inputs，走容错路径
    nearest_close = md.find("}}", content_start)
    if 0 <= nearest_close < sep_pos:
        return None
    skill_id = md[content_start:sep_pos].strip()
    if not skill_id:
        return None
    json_start = sep_pos + len(sep)
    while json_start < len(md) and md[json_start].isspace():
        json_start += 1
    json_end = _scan_json_end(md, json_start)
    if json_end < 0:
        return None
    k = json_end
    while k < len(md) and md[k].isspace():
        k += 1
    if not md.startswith("}}", k):
        return None
    return (k + 2, skill_id, md[json_start:json_end])


def _split_id_only(content: str) -> str:
    """容错路径：整段当 skill_id（无 inputs）。"""
    return content.strip()


async def render_skills(md: str) -> str:
    """执行并替换报告中的 skill 标记；失败降级为占位文本。"""
    markers = _find_markers(md)
    if not markers:
        return md

    parts: list[str] = []
    last = 0
    for start, end, skill_id, raw_inputs in markers:
        parts.append(md[last:start])
        inputs, err = _parse_inputs(raw_inputs)
        if err:
            parts.append(_fallback(skill_id, err))
            last = end
            continue
        result = await invoke_skill(skill_id, inputs)
        if not result.ok or result.artifact is None:
            parts.append(_fallback(skill_id, result.error or "unknown error"))
        elif result.artifact.content:
            parts.append(result.artifact.content)
        elif result.artifact.url:
            parts.append(f"[{skill_id}]({result.artifact.url})")
        else:
            parts.append(_fallback(skill_id, "empty artifact"))
        last = end

    parts.append(md[last:])
    rendered = "".join(parts)
    logger.info("已渲染 %d 个技能占位符", len(markers))
    return rendered

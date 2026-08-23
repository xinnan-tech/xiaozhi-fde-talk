"""i18n 键值齐平检查：跨多语文件比对，确保每个 key 在每种语言下都有翻译。

CI 调用：python -m backend.scripts.check_i18n_parity
- 退出码 0：所有 locale 覆盖完整
- 退出码 1：缺失/多余/类型不一致的 key

覆盖两组 locale：
1. 后端（backend/app/core/i18n/data/*.json）—— 平铺 dot-key
2. 前端（frontend/src/locales/*.json）—— 嵌套对象，扁平化为 dot-key 比对
   （"_meta" 这种元字段不参与）

比对策略：以「超集」为基准——任何一种语言有的 key，其他语言必须有。
同一语言下多个文件重复出现（zh-CN.json vs zh_CN.json）合并去重。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DATA = REPO_ROOT / "backend" / "app" / "core" / "i18n" / "data"
FRONTEND_DATA = REPO_ROOT / "frontend" / "src" / "locales"

# 后端 i18n 把 BCP-47 短横写法定为 canonical：SUPPORTED 集合决定有效语种；
# 历史数据文件两种命名都存在（en-US.json 与 en_US.json）—— 合并去重。
_META_KEYS = {"_meta"}


def _flatten(obj: dict, prefix: str = "") -> dict[str, object]:
    """嵌套 JSON 扁平化为 dot-key；遇到非 dict 节点直接取值。"""
    out: dict[str, object] = {}
    for k, v in obj.items():
        if k in _META_KEYS:
            continue
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _load_locale_files(directory: Path, suffixes: Iterable[str]) -> dict[str, dict]:
    """加载目录下所有 *.{suffix} JSON，按 BCP-47 短横写法归并。

    en_US.json 与 en-US.json 同时存在时取 key 并集（不去 value，保留各文件
    自己的翻译——但 key 集合以并集计，触发其他语种必须也覆盖）。
    """
    by_lang: dict[str, dict] = {}
    for path in sorted(directory.glob("*.json")):
        lang = path.stem.replace("_", "-")
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
        flat = _flatten(raw) if any(isinstance(v, dict) for v in raw.values()) else raw
        # 同语种多个文件：合并 key（值取第一个出现的）
        bucket = by_lang.setdefault(lang, {})
        for k, v in flat.items():
            bucket.setdefault(k, v)
    return by_lang


def _check_parity(by_lang: dict[str, dict], label: str) -> list[str]:
    """比对一组多语字典，返回问题清单。"""
    if len(by_lang) < 2:
        return []
    union: set[str] = set()
    for keys in by_lang.values():
        union |= set(keys.keys())
    problems: list[str] = []
    for lang in sorted(by_lang):
        missing = union - set(by_lang[lang].keys())
        if missing:
            preview = ", ".join(sorted(missing)[:5])
            more = f" (+{len(missing) - 5})" if len(missing) > 5 else ""
            problems.append(f"  [{label} {lang}] 缺 {len(missing)} key: {preview}{more}")
    return problems


def _check_value_types(by_lang: dict[str, dict], label: str) -> list[str]:
    """同一 key 在不同语种下 value 类型必须一致——避免一边 str 一边 list。"""
    problems: list[str] = []
    keys = set()
    for d in by_lang.values():
        keys |= set(d.keys())
    for k in sorted(keys):
        types = {type(v).__name__ for d in by_lang.values() for v in [d.get(k)] if k in d}
        if len(types) > 1:
            problems.append(f"  [{label}] key {k!r} value 类型不一致：{types}")
    return problems


def main() -> int:
    backend = _load_locale_files(BACKEND_DATA, ("json",))
    frontend = _load_locale_files(FRONTEND_DATA, ("json",))

    problems: list[str] = []
    problems.extend(_check_parity(backend, "backend"))
    problems.extend(_check_parity(frontend, "frontend"))
    problems.extend(_check_value_types(backend, "backend"))
    problems.extend(_check_value_types(frontend, "frontend"))

    print(f"后端语种：{sorted(backend)}（{sum(len(v) for v in backend.values())} key 总和）")
    print(f"前端语种：{sorted(frontend)}（{sum(len(v) for v in frontend.values())} key 总和）")
    if problems:
        print("\nFAIL — i18n 不齐平：")
        for p in problems:
            print(p)
        return 1
    print("\nOK — i18n 全语种齐平")
    return 0


if __name__ == "__main__":
    sys.exit(main())

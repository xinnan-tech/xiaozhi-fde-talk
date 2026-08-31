"""迁移文件约定：单链、编号连续、文件名前缀 == revision id。

- revision id 全局唯一，4 位数字，文件名以其为前缀（NNNN_描述.py）；
- 从 0001 起编号连续——新增迁移取当前最大号 +1，禁止跳号占位；
- down_revision 串成单链，全目录只有一个 head。
"""
from __future__ import annotations

import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

_REVISION_RE = re.compile(r'^revision(?::[^=\n]+)?\s*=\s*["\']([^"\']+)["\']', re.M)
_DOWN_RE = re.compile(r"^down_revision(?::[^=\n]+)?\s*=\s*(.+)$", re.M)


def _load() -> list[tuple[str, str, str | None]]:
    """[(文件名, revision, down_revision)]；down_revision 规整为 str|None。"""
    out: list[tuple[str, str, str | None]] = []
    for py in sorted(VERSIONS_DIR.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        m = _REVISION_RE.search(text)
        assert m is not None, f"{py.name} 缺 revision 声明"
        down = _DOWN_RE.search(text)
        assert down is not None, f"{py.name} 缺 down_revision 声明"
        raw = down.group(1).strip()
        down_rev = None if raw == "None" else raw.strip("\"'")
        out.append((py.name, m.group(1), down_rev))
    return out


def test_migrations_single_contiguous_chain():
    files = _load()
    assert files, "migrations/versions 为空？"
    ids = [rev for _, rev, _ in files]

    # 文件名前缀 == revision id（NNNN_描述.py），id 为 4 位数字
    for name, rev, _ in files:
        assert re.fullmatch(r"\d{4}", rev), f"{name}: revision {rev!r} 不是 4 位数字"
        assert name.startswith(rev + "_"), f"{name}: 文件名前缀应等于 revision {rev}"

    # revision id 唯一（重号会让 alembic 拒载）
    assert len(ids) == len(set(ids)), f"revision id 重复：{sorted(ids)}"

    # 编号恰好是 1..N：禁止跳号——新增迁移取当前最大号 +1
    nums = sorted(int(r) for r in ids)
    assert nums == list(range(1, len(nums) + 1)), (
        f"编号应从 0001 连续，现有 {[f'{n:04d}' for n in nums]}；"
        "新增迁移请取当前最大号 +1"
    )

    # 单链：按编号排序后 down_revision 依次指向前一个，首个为 None
    ordered = sorted(files, key=lambda t: int(t[1]))
    assert ordered[0][2] is None, f"{ordered[0][0]}: 首个迁移 down_revision 应为 None"
    for prev, cur in zip(ordered, ordered[1:]):
        assert cur[2] == prev[1], (
            f"{cur[0]}: down_revision 应指向 {prev[1]}（当前 {cur[2]!r}），保持单链"
        )

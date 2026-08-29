"""check_i18n_parity 里的 unused-enum 检测用临时数据跑单元测试：
- 全部引用 → 0 unused
- 部分引用 → 只列出未引用的
- 注释里的 Keys.XXX 字面量 → AST 不算
- 解析失败的 .py → 跳过，不崩
- enum 里有 alias（A = B）→ 不当成新条目
"""
from __future__ import annotations

import sys
from pathlib import Path

# pytest rootdir 是 backend/，但脚本位于 backend.scripts.*，运行时需要把仓
# 根加进 sys.path（CI 跑 `python -m backend.scripts.check_i18n_parity` 时仓
# 根天然在 path 里，pycharm/pytest 默认不会）。
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.scripts.check_i18n_parity import (  # noqa: E402
    _check_unused_enum_entries,
    _collect_keys_references,
    _parse_keys_enum,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _fake_messages(tmp_path: Path) -> Path:
    p = tmp_path / "messages.py"
    _write(
        p,
        "from enum import StrEnum\n"
        "class Keys(StrEnum):\n"
        "    FOO_USED = 'foo.used'\n"
        "    FOO_UNUSED = 'foo.unused'\n"
        "    BAR_USED = 'bar.used'\n"
        "    BAR_ALIAS = BAR_USED  # alias，不重复算\n"
        "    BAZ_USED = 'baz.used'\n"
        "    NOT_A_STR = 123  # 非 str 字面量，跳过\n",
    )
    return p


def test_parse_keys_enum_skips_alias_and_non_str(tmp_path: Path):
    mp = _fake_messages(tmp_path)
    parsed = _parse_keys_enum(mp)
    # alias 跳过；NOT_A_STR 跳过；剩 4 个
    assert parsed == {
        "FOO_USED": "foo.used",
        "FOO_UNUSED": "foo.unused",
        "BAR_USED": "bar.used",
        "BAZ_USED": "baz.used",
    }


def test_parse_keys_enum_supports_annotated_assignment(tmp_path: Path):
    """`NAME: str = "literal"` 这种带注解的写法也要能识别。"""
    p = tmp_path / "messages_ann.py"
    _write(
        p,
        "from enum import StrEnum\n"
        "class Keys(StrEnum):\n"
        "    FOO: str = 'foo.ann'\n"
        "    BAR = 'bar.plain'\n",
    )
    assert _parse_keys_enum(p) == {"FOO": "foo.ann", "BAR": "bar.plain"}


def test_collect_keys_references_ignores_comments_and_strings(tmp_path: Path):
    # 引用 + 注释/字符串里的伪引用混在一起
    src = tmp_path / "use_keys.py"
    _write(
        src,
        "from somewhere import Keys\n"
        "# 这是注释里的 Keys.COMMENT_ONLY，不应被算\n"
        "x = 'Keys.STRING_LITERAL_NOT_REAL'\n"
        "y = f'Keys.FSTRING_{x}'  # f-string 也不该算\n"
        "def use():\n"
        "    return Keys.FOO_USED\n"
        "    return Keys.BAR_USED  # 真引用\n",
    )
    refs = _collect_keys_references([tmp_path])
    assert "FOO_USED" in refs
    assert "BAR_USED" in refs
    assert "COMMENT_ONLY" not in refs
    assert "STRING_LITERAL_NOT_REAL" not in refs
    assert "BAZ_USED" not in refs  # 这文件没用过 BAZ_USED


def test_unused_detection_reports_only_unused_sorted(tmp_path: Path):
    mp = _fake_messages(tmp_path)
    src_dir = tmp_path / "src"
    _write(
        src_dir / "consumer.py",
        "from messages import Keys\n"
        "def a():\n"
        "    return Keys.FOO_USED\n"
        "def b():\n"
        "    return Keys.BAR_USED\n"
        "def c():\n"
        "    return Keys.BAZ_USED\n",
    )
    problems, total = _check_unused_enum_entries(mp, [src_dir])
    # _fake_messages 里 6 个字面量中 alias 和非 str 都被 _parse_keys_enum 跳过
    # → 只剩 4 个真条目：FOO_USED / FOO_UNUSED / BAR_USED / BAZ_USED
    assert total == 4
    # 只剩 FOO_UNUSED 未引用
    assert problems == [
        "  [unused] FOO_UNUSED = 'foo.unused' (代码里没出现 Keys.FOO_UNUSED)"
    ]


def test_unused_detection_clean_when_all_used(tmp_path: Path):
    mp = _fake_messages(tmp_path)
    src = tmp_path / "all_used.py"
    _write(
        src,
        "from messages import Keys\n"
        "Keys.FOO_USED.value\n"
        "Keys.FOO_UNUSED.value\n"
        "Keys.BAR_USED.value\n"
        "Keys.BAZ_USED.value\n",
    )
    problems, total = _check_unused_enum_entries(mp, [tmp_path])
    assert total == 4
    assert problems == []


def test_unused_detection_handles_syntax_error_gracefully(tmp_path: Path):
    mp = _fake_messages(tmp_path)
    bad = tmp_path / "broken.py"
    _write(bad, "def this is not valid python !!!")
    good = tmp_path / "good.py"
    _write(
        good,
        "from messages import Keys\n"
        "Keys.FOO_USED.value\n",
    )
    # 坏文件不崩；BAR/BAZ 在 good.py 没引用，应被报
    problems, total = _check_unused_enum_entries(mp, [tmp_path])
    assert total == 4
    unused = [p.split()[1] for p in problems]
    assert unused == ["BAR_USED", "BAZ_USED", "FOO_UNUSED"]


def test_unused_detection_missing_source_root_is_noop(tmp_path: Path):
    """source_roots 指向不存在的目录时，不崩、返回全部 unused。"""
    mp = _fake_messages(tmp_path)
    problems, total = _check_unused_enum_entries(
        mp, [tmp_path / "does_not_exist"]
    )
    assert total == 4
    assert len(problems) == 4


def test_collect_keys_references_handles_dynamic_access(tmp_path: Path):
    """动态访问 `getattr(Keys, name)` / `Keys[name]` 拿不到具体 key，应
    被视为「所有 key 都被引用过」，防止只走动态路径的 key 被误判为死键。
    """
    mp = _fake_messages(tmp_path)
    src = tmp_path / "dynamic.py"
    _write(
        src,
        "from messages import Keys\n"
        "def f(name):\n"
        "    return getattr(Keys, name)\n"
        "def g(name):\n"
        "    return Keys[name]\n",
    )
    # 不传 known_keys 时，动态访问被静默忽略（保持旧行为）
    refs = _collect_keys_references([tmp_path])
    assert refs == set()
    # 传 known_keys 时，动态访问把所有 key 并入 used
    refs_with_keys = _collect_keys_references(
        [tmp_path], known_keys={"FOO_USED", "FOO_UNUSED", "BAR_USED", "BAZ_USED"}
    )
    assert refs_with_keys == {"FOO_USED", "FOO_UNUSED", "BAR_USED", "BAZ_USED"}
    # 在 _check_unused_enum_entries 路径下：动态访问让所有 key 都视为已用 → 0 problems
    problems, total = _check_unused_enum_entries(mp, [tmp_path])
    assert total == 4
    assert problems == []

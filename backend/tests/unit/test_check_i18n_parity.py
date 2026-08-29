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

# pycharm/pytest 跑时不带仓根，手动补。
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


def test_parse_keys_enum_handles_missing_file(tmp_path: Path):
    """messages.py 不存在 / 编码坏了 / 语法炸了 → 返回空 dict 而不是崩。"""
    missing = tmp_path / "does_not_exist.py"
    assert _parse_keys_enum(missing) == {}

    bad = tmp_path / "bad_encoding.py"
    bad.write_bytes(b"\xff\xfe not utf8")
    assert _parse_keys_enum(bad) == {}

    syntax = tmp_path / "syntax.py"
    _write(syntax, "def this is not valid python !!!")
    assert _parse_keys_enum(syntax) == {}


def test_collect_keys_references_ignores_comments_and_strings(tmp_path: Path):
    src = tmp_path / "use_keys.py"
    _write(
        src,
        "from somewhere import Keys\n"
        "# 这是注释里的 Keys.COMMENT_ONLY，不应被算\n"
        "x = 'Keys.STRING_LITERAL_NOT_REAL'\n"
        "y = f'Keys.FSTRING_{x}'\n"
        "def use():\n"
        "    return Keys.FOO_USED\n"
        "    return Keys.BAR_USED\n",
    )
    static, dynamic_only = _collect_keys_references([tmp_path])
    assert "FOO_USED" in static
    assert "BAR_USED" in static
    assert "COMMENT_ONLY" not in static
    assert "STRING_LITERAL_NOT_REAL" not in static
    assert "BAZ_USED" not in static
    assert dynamic_only == set()


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
    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [src_dir]
    )
    assert total == 4
    assert static_count == 3
    assert dynamic_count == 0
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
    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path]
    )
    assert total == 4
    assert static_count == 4
    assert dynamic_count == 0
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
    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path]
    )
    assert total == 4
    assert static_count == 1
    assert dynamic_count == 0
    unused = [p.split()[1] for p in problems]
    assert unused == ["BAR_USED", "BAZ_USED", "FOO_UNUSED"]


def test_unused_detection_missing_source_root_is_noop(tmp_path: Path):
    """source_roots 指向不存在的目录时，不崩、返回全部 unused。"""
    mp = _fake_messages(tmp_path)
    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path / "does_not_exist"]
    )
    assert total == 4
    assert static_count == 0
    assert dynamic_count == 0
    assert len(problems) == 4


def test_collect_keys_references_handles_dynamic_access(tmp_path: Path):
    """动态访问 `getattr(Keys, name)` / `Keys[name]` 拿不到具体 key，本文件
    未静态引用的那部分 known_keys 进 dynamic_only；其他文件静态引用过的
    key 不算「仅动态可达」。"""
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
    static, dynamic_only = _collect_keys_references([tmp_path])
    assert static == set()
    assert dynamic_only == set()

    static, dynamic_only = _collect_keys_references(
        [tmp_path], known_keys={"FOO_USED", "FOO_UNUSED", "BAR_USED", "BAZ_USED"}
    )
    assert static == set()
    assert dynamic_only == {"FOO_USED", "FOO_UNUSED", "BAR_USED", "BAZ_USED"}

    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path]
    )
    assert total == 4
    assert static_count == 0
    assert dynamic_count == 4
    assert problems == []


def test_dynamic_only_subtracts_static_used_in_other_files(tmp_path: Path):
    """一个文件静态引用 + 另一个文件动态访问：被静态引用过的 key 不算「仅
    动态可达」。"""
    mp = _fake_messages(tmp_path)
    static_only = tmp_path / "static_user.py"
    _write(
        static_only,
        "from messages import Keys\n"
        "x = Keys.FOO_USED\n",
    )
    dynamic = tmp_path / "dynamic_user.py"
    _write(
        dynamic,
        "from messages import Keys\n"
        "def f(name):\n"
        "    return getattr(Keys, name)\n",
    )
    static, dynamic_only = _collect_keys_references(
        [tmp_path], known_keys={"FOO_USED", "FOO_UNUSED", "BAR_USED", "BAZ_USED"}
    )
    assert "FOO_USED" in static
    # FOO_USED 在静态文件出现过，全局胜出，不算 dynamic_only
    assert "FOO_USED" not in dynamic_only
    # 没在任何文件静态出现过的 3 个 key，进 dynamic_only
    assert dynamic_only == {"FOO_UNUSED", "BAR_USED", "BAZ_USED"}

    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path]
    )
    assert total == 4
    assert static_count == 1
    assert dynamic_count == 3
    assert problems == []


def test_subscript_store_and_del_not_dynamic(tmp_path: Path):
    """`Keys[x] = y`（Store）和 `del Keys[x]`（Del）不算动态读取——防止
    用赋值语句伪装成「全部已用」。"""
    mp = _fake_messages(tmp_path)
    src = tmp_path / "store.py"
    _write(
        src,
        "from messages import Keys\n"
        "def f():\n"
        "    Keys['whatever'] = 1\n"
        "del Keys['other']\n",
    )
    static, dynamic_only = _collect_keys_references(
        [tmp_path], known_keys={"FOO_USED", "FOO_UNUSED", "BAR_USED", "BAZ_USED"}
    )
    assert static == set()
    assert dynamic_only == set()

    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path]
    )
    assert total == 4
    assert static_count == 0
    assert dynamic_count == 0
    unused = {p.split()[1] for p in problems}
    assert unused == {"FOO_USED", "FOO_UNUSED", "BAR_USED", "BAZ_USED"}

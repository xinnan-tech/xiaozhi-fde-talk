"""check_i18n_parity 里的 unused-enum 检测用临时数据跑单元测试：
- 全部引用 → 0 unused
- 部分引用 → 只列出未引用的
- 注释里的 Keys.XXX 字面量 → AST 不算
- 解析失败的 .py → 跳过，不崩
- enum 里的 alias（A = B）→ 展开进 name_to_value，value 取自原条目
- import 别名（`from ... import Keys as K`）→ 匹配主体一并接受
"""
from __future__ import annotations

import sys
from pathlib import Path

# 直接跑本文件时 sys.path 不含仓根，手动补。
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

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
        "    BAR_ALIAS = BAR_USED  # alias 展开，value 取自 BAR_USED\n"
        "    BAZ_USED = 'baz.used'\n"
        "    NOT_A_STR = 123  # 非 str 字面量，跳过\n",
    )
    return p


def test_parse_keys_enum_expands_alias_and_skips_non_str(tmp_path: Path):
    mp = _fake_messages(tmp_path)
    parsed = _parse_keys_enum(mp)
    # alias 展开：BAR_ALIAS 合并进 name_to_value，value 与 BAR_USED 相同
    assert parsed == {
        "FOO_USED": "foo.used",
        "FOO_UNUSED": "foo.unused",
        "BAR_USED": "bar.used",
        "BAR_ALIAS": "bar.used",
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


def test_parse_keys_enum_raises_on_missing_or_broken_file(tmp_path: Path):
    """messages.py 不存在 / 编码坏了 / 语法炸了 → 抛异常，由 caller 推
    problem 让 CI 红，避免整个 dead-key 检测永久静默 no-op。"""
    missing = tmp_path / "does_not_exist.py"
    with pytest.raises(FileNotFoundError):
        _parse_keys_enum(missing)

    bad = tmp_path / "bad_encoding.py"
    bad.write_bytes(b"\xff\xfe not utf8")
    with pytest.raises(UnicodeDecodeError):
        _parse_keys_enum(bad)

    syntax = tmp_path / "syntax.py"
    _write(syntax, "def this is not valid python !!!")
    with pytest.raises(SyntaxError):
        _parse_keys_enum(syntax)


def test_unused_detection_reports_error_when_messages_missing(tmp_path: Path):
    """messages.py 缺失 → 推一条 problem，total/static/dynamic 全 0。"""
    missing = tmp_path / "does_not_exist.py"
    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        missing, [tmp_path]
    )
    assert total == 0
    assert static_count == 0
    assert dynamic_count == 0
    assert len(problems) == 1
    assert "缺失" in problems[0] or "解析失败" in problems[0]


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
    # alias BAR_ALIAS 展开后也算 enum 条目，但代码没引用它 → 报为 unused
    assert total == 5
    assert static_count == 3
    assert dynamic_count == 0
    assert problems == [
        "  [unused] BAR_ALIAS = 'bar.used' (代码里没出现 Keys.BAR_ALIAS)",
        "  [unused] FOO_UNUSED = 'foo.unused' (代码里没出现 Keys.FOO_UNUSED)",
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
        "Keys.BAR_ALIAS.value\n"
        "Keys.BAZ_USED.value\n",
    )
    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path]
    )
    assert total == 5  # alias 展开后多一个 BAR_ALIAS
    assert static_count == 5
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
    assert total == 5  # alias 展开后多一个 BAR_ALIAS
    assert static_count == 1
    assert dynamic_count == 0
    unused = [p.split()[1] for p in problems]
    assert unused == ["BAR_ALIAS", "BAR_USED", "BAZ_USED", "FOO_UNUSED"]


def test_unused_detection_missing_source_root_is_noop(tmp_path: Path):
    """source_roots 指向不存在的目录时，不崩、返回全部 unused。"""
    mp = _fake_messages(tmp_path)
    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path / "does_not_exist"]
    )
    assert total == 5  # alias 展开后多一个 BAR_ALIAS
    assert static_count == 0
    assert dynamic_count == 0
    assert len(problems) == 5


def test_collect_keys_references_handles_dynamic_access(tmp_path: Path):
    """动态访问 `getattr(Keys, name)` / `Keys[name]` 拿不到具体 key——纯
    动态访问、file_static 为空的文件不能用作 dynamic 兜底，否则整套检测
    静默失效（known_keys 全部吞掉，全局相减后 unused_names 永远为空）。"""
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
    # file_static 为空 → 不触发兜底，dynamic_only 仍是空集
    assert dynamic_only == set()

    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path]
    )
    # 文件唯一接触 Keys 的方式就是动态访问且静态为空 → 全部 enum 条目报为 unused
    assert total == 5
    assert static_count == 0
    assert dynamic_count == 0
    assert len(problems) == 5


def test_dynamic_only_subtracts_static_used_in_same_file(tmp_path: Path):
    """同一文件同时有静态引用 + 动态访问：本文件静态引用过的 key 不算「仅
    动态可达」，未在本文件静态引用的 known_keys 进 dynamic_only。要求
    file_static ≥ 1 才允许该文件触发 dynamic 兜底。"""
    mp = _fake_messages(tmp_path)
    mixed = tmp_path / "mixed_user.py"
    _write(
        mixed,
        "from messages import Keys\n"
        "x = Keys.FOO_USED  # 静态\n"
        "def f(name):\n"
        "    return getattr(Keys, name)  # 动态\n",
    )
    static, dynamic_only = _collect_keys_references(
        [tmp_path], known_keys=set(_parse_keys_enum(mp).keys())
    )
    assert "FOO_USED" in static
    # FOO_USED 在本文件静态出现过，全局胜出，不算 dynamic_only
    assert "FOO_USED" not in dynamic_only
    # 本文件未静态引用过的 4 个进 dynamic_only（含 BAR_ALIAS）
    assert dynamic_only == {"FOO_UNUSED", "BAR_USED", "BAR_ALIAS", "BAZ_USED"}

    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path]
    )
    assert total == 5
    assert static_count == 1
    assert dynamic_count == 4
    assert problems == []


def test_alias_name_counts_as_used_when_referenced_via_alias(tmp_path: Path):
    """enum alias 展开进 name_to_value 后，代码引用 alias 名（`Keys.BAR_ALIAS`）
    也能被 AST 抓到——alias 名不再被错误地「永远认为死键」。"""
    mp = _fake_messages(tmp_path)
    src = tmp_path / "alias_user.py"
    _write(
        src,
        "from messages import Keys\n"
        "x = Keys.BAR_ALIAS  # 只引 alias 名\n",
    )
    static, _ = _collect_keys_references(
        [tmp_path], known_keys={"FOO_USED", "FOO_UNUSED", "BAR_USED", "BAR_ALIAS", "BAZ_USED"}
    )
    # alias 名被静态引用
    assert "BAR_ALIAS" in static

    problems, total, static_count, dynamic_count = _check_unused_enum_entries(
        mp, [tmp_path]
    )
    # 只引了 alias 名 → 原名 BAR_USED 仍在 unused 中（AST 无法跨 alias
    # 关联原名），但 alias 名本身不算死键
    assert static_count == 1
    unused = {p.split()[1] for p in problems}
    assert "BAR_ALIAS" not in unused
    assert "BAR_USED" in unused


def test_collect_keys_references_handles_import_alias(tmp_path: Path):
    """`from ... import Keys as K; K.FOO` 这种 import 别名也要能识别——
    主体是同一枚举，attr 名仍按原 enum 名记录。"""
    src = tmp_path / "alias_import.py"
    _write(
        src,
        "from app.core.i18n.messages import Keys as K\n"
        "x = K.FOO_USED\n"
        "y = K['BAR_USED']\n",
    )
    static, dynamic_only = _collect_keys_references(
        [tmp_path], known_keys={"FOO_USED", "BAR_USED"}
    )
    assert "FOO_USED" in static
    # K['BAR_USED'] 是 Load ctx 的 Subscript → 触发 dynamic 兜底
    assert "BAR_USED" in dynamic_only


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
    # alias 展开后多一个 BAR_ALIAS，全部都报 unused
    assert total == 5
    assert static_count == 0
    assert dynamic_count == 0
    unused = {p.split()[1] for p in problems}
    assert unused == {"FOO_USED", "FOO_UNUSED", "BAR_USED", "BAR_ALIAS", "BAZ_USED"}

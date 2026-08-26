"""issue #77：about 页在未登录状态下访问 /api/v1/version 不该触发"登录过期"toast。

后端已改鉴权为可选（匿名返 200 + {"version": ""}），前端 about 页必须把
空串等同 null —— hasBothVersions 为 false 时降级为只显示前端版本，不出
现 "v" + 空字符串的诡异布局。本测试锁住两个契约：
1. hasBothVersions 用 !!backendVersion.value（truthy），不用 !== null
2. 注释或 catch 里说明匿名场景 backendVersion 是空字符串而非 null
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ABOUT = ROOT / "src" / "views" / "about" / "index.vue"
API_VERSION = ROOT / "src" / "api" / "version.ts"


def _script_block(text: str) -> str:
    start = text.index("<script")
    end = text.index("</script>", start)
    return text[start:end]


def test_has_both_versions_uses_truthy_check():
    """hasBothVersions 必须把空串当未拉到：!!backendVersion.value。

    旧实现 `backendVersion.value !== null` 会让匿名返的 "" 通过，单行
    布局被破坏显示成 "v"（空）+ 后端版本（空）。"""
    script = _script_block(ABOUT.read_text(encoding="utf-8"))
    assert "!!backendVersion.value" in script, (
        "hasBothVersions 必须用 !!backendVersion.value，空字符串才走单行降级"
    )
    assert "backendVersion.value !== null" not in script, (
        "旧 !== null 校验会让匿名空串逃过降级，显示成空 v"
    )


def test_anonymous_version_scenario_documented():
    """源码里至少一处说明匿名访问 → 空字符串 → 当 null 处理。"""
    script = _script_block(ABOUT.read_text(encoding="utf-8"))
    # 注释或逻辑里至少出现"匿名"/"空字符串"/"issue #77"其一作为契约提示
    has_anon_hint = (
        "匿名" in script
        or "issue #77" in script
        or "空字符串" in script
    )
    assert has_anon_hint, (
        "about 页源码里应说明匿名返空串的契约，否则后人改逻辑会漏"
    )


def test_api_version_doc_mentions_optional_auth():
    """getBackendVersion 的注释必须说明后端用可选鉴权（匿名返空版本）。"""
    text = API_VERSION.read_text(encoding="utf-8")
    assert "get_current_user_optional" in text or "匿名" in text, (
        "getBackendVersion 注释应说明匿名返空版本的契约"
    )
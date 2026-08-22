"""锁死 modulepreload 限到 6 chunk（B3 方案）。

原因：HTTP/1.1 单 origin 6 并发限制，浏览器打开页面时只能同时拉 6 个
modulepreload。vite 默认会预热入口路由所有直接依赖（实测 28 个），导致
4G 下首屏排队 5 批 ≈ 1s。本方案白名单过滤到 6 个关键 chunk。

注意：测试不依赖 modulepreload 数量 = 6（vite 后续版本可能改默认）；只
断言 ≤ 6 + 白名单内全在 + 白名单外（已知非关键）不在。
"""
import re
from pathlib import Path

DIST = Path(__file__).resolve().parents[2] / "dist" / "index.html"
ENTRY = Path(__file__).resolve().parents[2] / "index.html"
MODULEPRELOAD_RE = re.compile(
    r'<link\s+rel="modulepreload"[^>]*?href="([^"]+)"', re.IGNORECASE
)

WHITELIST = (
    "vue-vendor",
    "element-plus-message",
    "element-plus-form",
    "element-plus-input",
    "element-plus-dialog",
    "element-plus-button",
)


def _read_hrefs() -> list[str]:
    target = DIST if DIST.is_file() else ENTRY
    if not target.is_file():
        import pytest
        pytest.skip(f"dist/index.html 与 index.html 都不存在；先跑 pnpm build")
    return MODULEPRELOAD_RE.findall(target.read_text(encoding="utf-8"))


def test_modulepreload_count_at_most_six():
    """modulepreload 总数 ≤ 6（HTTP/1.1 6 并发限制）。"""
    hrefs = _read_hrefs()
    assert len(hrefs) <= 6, (
        f"modulepreload 有 {len(hrefs)} 个（{hrefs}）；超过 6 会触发 HTTP/1.1 排队"
    )


def test_modulepreload_whitelist_present():
    """白名单 6 个 chunk 必须全部 modulepreload。"""
    hrefs = _read_hrefs()
    missing = [w for w in WHITELIST if not any(w in h for h in hrefs)]
    assert not missing, (
        f"白名单 chunk 缺失 modulepreload：{missing}；"
        "首屏关键组件延迟加载会导致按钮点击 / 表单渲染慢"
    )


def test_modulepreload_no_extra_critical():
    """非白名单的高频组件不应 modulepreload（保证白名单真的过滤了，不是退化到 vite 默认）。"""
    hrefs = _read_hrefs()
    # 已知应该被排除的（懒加载）高频组件抽样
    expected_lazy = ("element-plus-table", "element-plus-tree", "element-plus-menu")
    leaked = [w for w in expected_lazy if any(w in h for h in hrefs)]
    assert not leaked, (
        f"懒加载 chunk 不应 modulepreload：{leaked}；"
        "白名单 resolveDependencies 没生效"
    )

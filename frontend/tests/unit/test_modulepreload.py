"""验证 vite 自动 modulepreload 覆盖关键 chunk（vue-vendor / element-plus 拆 chunk 后）。

前提：Task 1 已把 element-plus 拆成多 chunk；vite 应自动为每个直接 dependency
chunk 注入 modulepreload。如果只 modulepreload 主入口，没预加载 vue-vendor /
element-plus 任一 chunk，说明 modulePreload 配置需要调。

测试不依赖 modulepreload 数量阈值（vite 不同版本默认数量会变）；只断言
「关键 vendor chunk 是否被 modulepreload」+「href 路径合法（不是字面 [hash]）」。
"""
import re
from pathlib import Path

DIST = Path(__file__).resolve().parents[2] / "dist" / "index.html"
ENTRY_HTML = Path(__file__).resolve().parents[2] / "index.html"

MODULEPRELOAD_RE = re.compile(
    r'<link\s+rel="modulepreload"[^>]*?href="([^"]+)"', re.IGNORECASE
)


def _read_modulepreload_hrefs() -> list[str]:
    """从 dist/index.html 读 modulepreload hrefs（dist 不存在则读源模板兜底）。"""
    target = DIST if DIST.is_file() else ENTRY_HTML
    if not target.is_file():
        import pytest
        pytest.skip(f"dist/index.html 与 index.html 都不存在；先跑 pnpm build")
    text = target.read_text(encoding="utf-8")
    return MODULEPRELOAD_RE.findall(text)


def test_modulepreload_exists():
    hrefs = _read_modulepreload_hrefs()
    assert hrefs, "index.html 缺 modulepreload link"


def test_modulepreload_hrefs_resolve():
    """所有 modulepreload href 应是合法路径（不能是字面 [hash]）。"""
    hrefs = _read_modulepreload_hrefs()
    for h in hrefs:
        assert "[hash]" not in h, f"modulepreload href 含字面 [hash]：{h}（Vite 不替换此占位符，会 404）"
        assert h.startswith("/") or h.startswith("http"), f"href 不是绝对路径：{h}"


def test_modulepreload_includes_vue_vendor_or_element_plus():
    """关键 vendor chunk 应被 modulepreload 之一指向。"""
    hrefs = _read_modulepreload_hrefs()
    has_key = any(
        ("vue-vendor" in h) or ("element-plus" in h) or ("vendor" in h)
        for h in hrefs
    )
    assert has_key, (
        f"modulepreload 没指向关键 vendor chunk：{hrefs}；"
        "考虑在 vite.config.ts 调 build.modulePreload.resolveDependencies"
    )

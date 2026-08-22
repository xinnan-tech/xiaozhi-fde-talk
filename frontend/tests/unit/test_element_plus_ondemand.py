"""锁死 element-plus 已切到 unplugin 自动按需引入 + 删 manualChunks 强制合 chunk。

历史问题：
1. plugins/elementPlus.ts 手动 import 41 个 ElXxx 全量打包 → element-plus chunk ~800KB
2. src/**/*.{vue,ts} 还可能直接 import from "element-plus" → 绕过按需引入
3. vite.config.ts:99-103 manualChunks 把所有 element-plus 强制并入一个 chunk，
   即便按需引入也会被兜回单 chunk
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def test_plugin_file_removed():
    f = SRC / "plugins" / "elementPlus.ts"
    assert not f.is_file(), f"{f} 应删除；改 unplugin 后无存在意义"


def test_no_direct_element_plus_import_in_src():
    """src 全扫：禁止 from "element-plus" 直接 import（unplugin-auto-import 会处理）。"""
    offenders = []
    for path in SRC.rglob("*.vue"):
        text = path.read_text(encoding="utf-8")
        if re.search(r'from\s+["\']element-plus["\']', text):
            offenders.append(path.relative_to(ROOT))
    for path in SRC.rglob("*.ts"):
        text = path.read_text(encoding="utf-8")
        if re.search(r'from\s+["\']element-plus["\']', text):
            offenders.append(path.relative_to(ROOT))
    assert not offenders, (
        f"以下文件还直接 import from 'element-plus'：{offenders}；"
        f"应改用 unplugin-auto-import（直接 <ElXxx> 标签或 ElMessage() 调用即可）"
    )


def test_vite_config_has_unplugin():
    cfg = (ROOT / "vite.config.ts").read_text(encoding="utf-8")
    assert "unplugin-vue-components" in cfg
    assert "ElementPlusResolver" in cfg


def test_main_ts_no_bulk_element_plus():
    main_ts = (SRC / "main.ts").read_text(encoding="utf-8")
    assert 'element-plus/dist/index.css' not in main_ts
    assert "useElementPlus" not in main_ts
    assert 'from "@/plugins/elementPlus"' not in main_ts


def test_manual_chunks_no_element_plus():
    """vite manualChunks 不应再硬塞 element-plus 到单 chunk。"""
    cfg = (ROOT / "vite.config.ts").read_text(encoding="utf-8")
    # 允许注释里提，但代码块不能有 `return "element-plus"` 强制合 chunk
    assert 'return "element-plus"' not in cfg, (
        'vite.config.ts manualChunks 还有 return "element-plus"，会把按需引入的 element-plus 强制并回单 chunk'
    )

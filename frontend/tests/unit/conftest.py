"""frontend 单测 conftest。

辅助：当被测测试的参数里含 'dist' 字样、且 dist 目录不存在时自动 SKIP，
避免 "file-not-found" 假红。"""
from __future__ import annotations
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIST = PROJECT_ROOT / "dist"


@pytest.fixture(autouse=True)
def _skip_when_dist_missing(request):
    """被测目标在 dist 产物里的测试，自动 skip 当 dist 不存在。"""
    if any("dist" in str(arg) for arg in request.node.funcargs.values() if isinstance(arg, (str, Path))):
        if not DIST.is_dir():
            pytest.skip(f"dist 目录不存在（{DIST}）；先跑 pnpm build")

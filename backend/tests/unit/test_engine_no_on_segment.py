"""P3-8 · engine.on_segment 是死代码，删除并验证无调用方。

S1: grep 确认仓内无 engine.on_segment 的订阅方（spec 推荐删）。本测试为防回归：
任何改动重新添加 .on_segment() 调用必须显式更新此测试。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = BACKEND_ROOT / "app" / "services" / "coaching" / "engine.py"


def test_no_on_segment_method_in_engine():
    """engine.py 不应再有 on_segment 方法定义。"""
    src = ENGINE_PY.read_text(encoding="utf-8")
    assert "async def on_segment" not in src, (
        "engine.on_segment 死代码重新引入——确认无订阅方后删除"
    )


def test_no_on_segment_callers():
    """app/ 内任何地方都不应出现 on_segment（无声明、无调用）。"""
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", "on_segment", str(BACKEND_ROOT / "app")],
        capture_output=True,
        text=True,
    )
    # grep 退出码 1 = 无匹配
    assert result.returncode != 0, f"on_segment 仍有引用:\n{result.stdout}"

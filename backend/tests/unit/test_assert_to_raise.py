from __future__ import annotations
import subprocess, sys


def test_validate_prod_raises_under_opt():
    """python -O 剥离 assert，但显式 raise 仍生效。"""
    code = (
        "from app.core.settings import Settings; "
        "s=Settings(env='prod', db_url='sqlite:///./x.db'); "
        "print('NO_RAISE')"
    )
    out = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True)
    # 显式 raise 下 Settings 构造应非零退出（ValueError），不会打印 NO_RAISE
    assert out.returncode != 0
    assert "NO_RAISE" not in out.stdout
    assert "生产环境禁止使用 SQLite" in out.stderr

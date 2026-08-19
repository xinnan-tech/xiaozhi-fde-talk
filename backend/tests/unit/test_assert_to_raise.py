from __future__ import annotations
import subprocess, sys

from app.core.i18n.messages import Keys


def test_validate_prod_raises_under_opt():
    """python -O 剥离 assert，但显式 raise 仍生效。"""
    code = (
        "from app.core.settings import Settings; "
        "s=Settings(env='prod', db_url='sqlite:///./x.db'); "
        "print('NO_RAISE')"
    )
    out = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True)
    # 显式 raise 下 Settings 构造应非零退出（I18nError），不会打印 NO_RAISE
    assert out.returncode != 0
    assert "NO_RAISE" not in out.stdout
    # I18nError 的 str(e) 形如 "i18n:<code>{<params>}"，断言 i18n key 即可。
    assert Keys.SETTINGS_PROD_NO_SQLITE.value in out.stderr

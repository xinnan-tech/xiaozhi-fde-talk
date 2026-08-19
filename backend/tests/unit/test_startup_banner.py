import pytest

from app.core.i18n.messages import Keys
from app.core.i18n.translator import t


def test_admin_password_key_translates_zh_cn():
    """zh-CN translation is Chinese; the env-var name itself is ASCII so it
    appears verbatim in both locales. Asserting containment is correct; asserting
    startswith on an ASCII prefix in a Chinese string is meaningless."""
    msg = t(Keys.STARTUP_ADMIN_PASSWORD_MISSING.value, locale="zh-CN")
    assert "APP_ADMIN_PASSWORD" in msg
    assert msg != ""


def test_admin_password_key_translates_en_us():
    msg = t(Keys.STARTUP_ADMIN_PASSWORD_MISSING.value, locale="en-US")
    assert "APP_ADMIN_PASSWORD" in msg
    assert msg != ""

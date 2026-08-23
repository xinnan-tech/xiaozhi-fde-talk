"""密码强度策略回归测试。

覆盖 validate_password_strength 的四个分支；并固定弱密码黑名单的若干关键项
（包括「漏逗号拼接 bug \"admin123456qwerty123\"」与 bcrypt 72 字节 UTF-8 上限）。

测试是纯函数 / 集成小启动，不依赖任何外部服务。
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys
from app.core.password_policy import (
    MIN_LENGTH,
    PasswordTooLongError,
    WeakPasswordError,
    validate_password_strength,
)


# ---------- validate_password_strength 单元分支 ----------

def test_empty_password_raises_too_short():
    """空串 → I18nError(code=PASSWORD_TOO_SHORT)（不能漏到弱密码表分支）。"""
    with pytest.raises(I18nError) as ei:
        validate_password_strength("")
    assert ei.value.code == Keys.PASSWORD_TOO_SHORT.value


def test_short_password_raises_too_short():
    """< 8 位 → I18nError(code=PASSWORD_TOO_SHORT_MIN)，带长度参数。"""
    with pytest.raises(I18nError) as ei:
        validate_password_strength("a" * (MIN_LENGTH - 1))
    assert ei.value.code == Keys.PASSWORD_TOO_SHORT_MIN.value
    assert ei.value.params["min"] == MIN_LENGTH
    assert ei.value.params["actual"] == MIN_LENGTH - 1


def test_weak_password_raises_weak():
    """命中弱密码表 → WeakPasswordError。"""
    with pytest.raises(WeakPasswordError):
        validate_password_strength("password")


def test_strong_password_passes():
    """正常 8+ 位、不在表内 → 不抛。"""
    validate_password_strength("StrongP@ss-2026!")


def test_weak_match_is_case_insensitive():
    """大小写不敏感：\"PASSWORD\" 也算命中。"""
    with pytest.raises(WeakPasswordError):
        validate_password_strength("PASSWORD")


# ---------- 弱密码表关键项回归（含漏逗号 bug 守卫）----------

@pytest.mark.parametrize("candidate", [
    "admin123456",  # 漏逗号 bug 前必须独立存在的项
    "qwerty123",    # 漏逗号 bug 前必须独立存在的项
    "12345678",     # 经典 8 位
])
def test_admin123456_and_qwerty123_are_independently_blacklisted(candidate: str):
    """\"admin123456\" 与 \"qwerty123\" 必须各自独立在表内 —— 防止再次出现漏逗号
    被 Python 拼接成 \"admin123456qwerty123\"、两边反而都不在表的回归 bug。
    """
    with pytest.raises(WeakPasswordError):
        validate_password_strength(candidate)


# ---------- bcrypt 72 字节 UTF-8 上限 ----------

def test_long_ascii_password_raises():
    """纯 ASCII 超 72 字节 → PasswordTooLongError。"""
    too_long = "a" * 73
    with pytest.raises(PasswordTooLongError):
        validate_password_strength(too_long)


def test_72_byte_ascii_password_passes():
    """边界 72 字节（整 72 个 ASCII）→ 通过。"""
    validate_password_strength("a" * 72)


def test_long_multibyte_password_raises():
    """多字节字符（如中文）按 UTF-8 字节算，24 个汉字 = 72 字节 → 通过；
    25 个汉字 = 75 字节 → 拒。注意：字符数 < 73 但字节数 > 72 时也必须拒，
    避免 bcrypt 4.x 静默截断 / 5.x 抛裸 ValueError。
    """
    validate_password_strength("中" * 24)  # 72 字节
    with pytest.raises(PasswordTooLongError):
        validate_password_strength("中" * 25)  # 75 字节
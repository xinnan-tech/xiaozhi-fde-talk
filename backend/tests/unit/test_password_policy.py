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
    """< MIN_LENGTH 位 → I18nError(code=PASSWORD_TOO_SHORT_MIN)，带长度参数。"""
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
    """正常 12+ 位、≥ 3 字符类、不在表内 → 不抛。"""
    validate_password_strength("StrongP@ss-2026!")


def test_weak_match_is_case_insensitive():
    """大小写不敏感：\"PASSWORD\" 也算命中。"""
    with pytest.raises(WeakPasswordError):
        validate_password_strength("PASSWORD")


# ---------- Wave 3 P1 #24：12 字符 / ≥ 3 字符类 ----------

def test_11_char_password_rejected_for_length():
    """\"Password12!\" 11 字符 → PASSWORD_TOO_SHORT_MIN。"""
    with pytest.raises(I18nError) as ei:
        validate_password_strength("Password12!")  # 11 chars, < MIN_LENGTH=12
    assert ei.value.code == Keys.PASSWORD_TOO_SHORT_MIN.value


def test_tr0ub4dor_accepted():
    """\"Tr0ub4dor&3\" 实际 11 字符，MIN_LENGTH=12 下须补字符构成 12 字符 + 4 类 → 通过。"""
    # 经典 xkcd 口令原版 11 字符，加 1 符号凑齐 12 字符下限仍保持 4 类
    validate_password_strength("Tr0ub4dor&3!")


def test_low_entropy_password_rejected():
    """12 字符但仅 1 字符类（\"aaaaaaaaaaaa\"）→ PASSWORD_TOO_WEAK。"""
    with pytest.raises(WeakPasswordError):
        validate_password_strength("a" * 12)


def test_two_class_long_password_rejected():
    """12 字符 + 仅 2 类（\"abcdefghijkl\"）→ PASSWORD_TOO_WEAK（熵不足）。"""
    with pytest.raises(WeakPasswordError):
        validate_password_strength("abcdefghijkl")  # 12 chars all lowercase


def test_three_class_long_password_accepted():
    """12 字符 + 3 类（upper + lower + digit）→ 通过。"""
    validate_password_strength("Abcdefgh1234")  # upper + lower + digit = 3 类


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
    too_long = "a" * 73 + "B2!"  # 76 字节，必超；额外 3 字符凑 ≥ 3 类避免弱密码路径抢跑
    with pytest.raises(PasswordTooLongError):
        validate_password_strength(too_long)


def test_72_byte_ascii_password_passes():
    """边界 72 字节（混 4 类）→ 通过。"""
    # 72 字符共 72 字节，且必须 ≥ 3 类。改用混合类填充：a 60 + 12 symbols（!）。
    # 60 lowercase + 12 symbol = 2 类不够，加 3 字符大写 = 3 类。
    s = ("A" * 3) + ("a" * 57) + ("!" * 12)  # 3 + 57 + 12 = 72 字节；3 类
    assert len(s) == 72
    validate_password_strength(s)


def test_long_multibyte_password_raises():
    """多字节字符（如中文）按 UTF-8 字节算：每个汉字 3 字节。

    字符类检查扩展到「非 ASCII」也算 1 类（CJK 用户友好），必须混 1 个数字才能
    共 2 类（汉字 + digit）；再加 1 个符号达 ≥ 3 类，规避 weak 路径抢跑。
    """
    # 22 汉字 + 1 数字 + 1 符号 = 22*3+2 = 68 字节 + 3 类 → 通过
    validate_password_strength("中" * 22 + "1!")  # 68 字节
    # 24 汉字 + 1 数字 + 1 符号 = 72+2 = 74 字节 → 超 72 → PasswordTooLongError
    with pytest.raises(PasswordTooLongError):
        validate_password_strength("中" * 24 + "1!")  # 74 字节
    # 25 汉字 + 1 数字 = 75+1 = 76 字节 → 拒
    with pytest.raises(PasswordTooLongError):
        validate_password_strength("中" * 25 + "1")  # 76 字节
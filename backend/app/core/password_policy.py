"""admin 启动密码强度策略。

校验失败抛 I18nError（http_status=400），由调用方（Settings model_validator /
seed_dev_users）转译。最小长度 ≥ 8，且不能命中弱密码表（不区分大小写）。

"""
from __future__ import annotations

from app.core.i18n.errors import I18nError
from app.core.i18n.messages import Keys

# frozenset 不可变 + O(1) 查找；预 lower 后存，避免每次 lower
_WEAK_PASSWORDS: frozenset[str] = frozenset(p.lower() for p in (
    # --- 常见弱密码合并集：综合字典 top1000 截取 + NordPass 历年泄漏 top 100 ---
    "password",
    "1314wanana",
    "forbidden",
    "777admin",
    "admin777",
    "@admin123",
    "123@admin",
    "admin123",
    "123456789",
    "12345678",
    "11111111",
    "fill.com",
    "123123123",
    "00000000",
    "1234567890",
    "a123456789",
    "88888888",
    "147258369",
    "qq123456",
    "woaini1314",
    "123456abc",
    "987654321",
    "123456789a",
    "abc123456",
    "111222tianya",
    "123456aa",
    "aa123456",
    "789456123",
    "1111111111",
    "iloveyou",
    "woaini520",
    "woaini123",
    "111111111",
    "1qaz2wsx",
    "qwertyuiop",
    "5201314520",
    "asd123456",
    "31415926",
    "woaini521",
    "abcd1234",
    "asdfghjkl",
    "123456qq",
    "11223344",
    "123698745",
    "wangyut2",
    "zxcvbnm123",
    "qazwsxedc",
    "1q2w3e4r",
    "12345678910",
    "qwe123456",
    "123654789",
    "0000000000",
    "woaiwojia",
    "741852963",
    "5845201314",
    "aini1314",
    "0123456789",
    "123456123",
    "520520520",
    "q123456789",
    "qweasdzxc",
    "5845211314",
    "12301230",
    "qq123456789",
    "wocaonima",
    "qq123123",
    "a5201314",
    "a12345678",
    "asdasdasd",
    "a1234567",
    "135792468",
    "963852741",
    "3.1415926",
    "zhang123",
    "1233211234567",
    "25257758",
    "7708801314520",
    "999999999",
    "1357924680",
    "yahoo.com.cn",
    "123456789q",
    "12341234",
    "5841314520",
    "zxc123456",
    "yangyang",
    "123123qaz",
    "abcd123456",
    "as123456",
    "xiaoxiao",
    "000000000",
    "aaa123456",
    "110110110",
    "buzhidao",
    "admin123456",
    "qwerty123",
))

MIN_LENGTH = 8

# bcrypt 算法上限：密码按 UTF-8 编码后不得超过 72 字节。
# 4.x 静默截断（仅前 72 字节生效，攻击面扩大），5.x 直接抛裸 ValueError。
# 中文等多字节字符更易触发，故按字节而非字符数校验。
_BCRYPT_MAX_BYTES = 72


# Aliased: legacy classes keep working under `except PasswordTooShortError` /
# `except WeakPasswordError` etc. (e.g. tests/unit/test_password_policy.py).
WeakPasswordError = I18nError
PasswordTooShortError = I18nError
PasswordTooLongError = I18nError


def validate_password_strength(password: str) -> None:
    """校验密码强度。失败抛 I18nError（http_status=400）。

    规则：
    1. 长度 ≥ MIN_LENGTH（8）
    2. UTF-8 字节数 ≤ _BCRYPT_MAX_BYTES（72）
    3. 不在弱密码表中（不区分大小写）
    """
    if not password:
        raise I18nError(Keys.PASSWORD_TOO_SHORT, http_status=400)
    if len(password) < MIN_LENGTH:
        raise I18nError(
            Keys.PASSWORD_TOO_SHORT_MIN, http_status=400,
            min=MIN_LENGTH, actual=len(password),
        )
    # bcrypt 上限按字节算，避免多字节字符静默截断 / 抛裸异常
    byte_len = len(password.encode("utf-8"))
    if byte_len > _BCRYPT_MAX_BYTES:
        raise I18nError(
            Keys.PASSWORD_TOO_LONG, http_status=400,
            byte_len=byte_len, max=_BCRYPT_MAX_BYTES,
        )
    if password.lower() in _WEAK_PASSWORDS:
        raise I18nError(
            Keys.PASSWORD_TOO_WEAK, http_status=400,
            count=len(_WEAK_PASSWORDS),
        )

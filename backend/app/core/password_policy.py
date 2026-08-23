"""密码强度策略。

校验失败抛 I18nError（http_status=400），由调用方（注册 / 改密 / 重置密码）
转译。最小长度 ≥ 12，≥ 3 类字符（小写 / 大写 / 数字 / 符号），且不能命中弱密码
表（不区分大小写）。

字符类要求：NIST SP 800-63B 强调「熵」而非「复杂度」——12 字符以上 + 4 类固然理想，
但「3 类以上」是 mixin 友好的折中：纯字母数字口令（12 字符 random）约 71 bits，
比 12 字符同种字符（41 bits）显著更高，但又不强求符号（符号在很多密码管理器
生成器里默认就有，避免人手工输入时难记）。这一档与 NIST 2024 推荐同档。

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
    # --- Wave 3 扩充：漏逗号 bug 防御 + 历年 top 200 中段 ---
    "abc12345",
    "abcd123",
    "ab123456",
    "user123",
    "user1234",
    "pass123",
    "pass1234",
    "demo123",
    "demo1234",
    "root123",
    "root1234",
    "test123",
    "test1234",
    "qwerty1",
    "qwerty12",
    "1q2w3e",
    "1q2w3e4r5t",
    "q1w2e3r4",
    "1a2b3c4d",
    "p@ssw0rd",
    "p@ssword",
    "passw0rd",
    "pa55word",
    "passwd1",
    "login123",
    "welcome",
    "welcome1",
    "welcome123",
    "qwerty12345",
    "qaz123",
    "zaq12wsx",
    "changeme",
    "letmein",
    "letmein1",
    "trustno1",
    "master123",
    "master1234",
    "dragon123",
    "monkey123",
    "abcde12345",
    "abcdef123",
    "baseball",
    "baseball1",
    "football",
    "football1",
    "soccer123",
    "jordan23",
    "jordan123",
    "shadow123",
    "sunshine",
    "iloveu123",
    "michael1",
    "jennifer",
    "hunter12",
    "hunter123",
    "hunter2",
    "ranger123",
    "thomas123",
    "summer2026",
    "summer123",
    "summer2025",
    "winter2025",
    "winter2026",
    "secret123",
    "secret1234",
    "computer",
    "internet",
    "internet1",
    "server123",
    "mysql123",
    "oracle123",
    "linux123",
    "mongodb1",
    "database1",
    "sql123456",
    "pgsql123",
    "system123",
    "office123",
    "office2025",
    "office2026",
    "company1",
    "company12",
    "company123",
    "support1",
    "support123",
    "sa123456",
    "sa12345",
    "administrator",
    "administrator1",
    "nimda1234",
    "nimda12345",
    "testtest",
    "guest123",
    "guest1234",
    "temp1234",
    "temp12345",
    "temporary",
    "default1234",
    "default12345",
    "useradmin1",
    "superuser1",
    "super12345",
    "su123456",
    "backup1234",
    "service1234",
    "operator1",
))

# 长度下限提到 12：NIST SP 800-63B / NIST2024 推荐 ≥ 8 字符的密码外加无
# 复杂度要求；本系统作为会话凭证 + 改密可吊销，独立要求 ≥ 12 是 user-friendly
# 折中——比 8 安全、比 16 易用，能让密码管理器生成的 16 字符口令无感通过。
MIN_LENGTH = 12

# bcrypt 算法上限：密码按 UTF-8 编码后不得超过 72 字节。
# 4.x 静默截断（仅前 72 字节生效，攻击面扩大），5.x 直接抛裸 ValueError。
# 中文等多字节字符更易触发，故按字节而非字符数校验。
_BCRYPT_MAX_BYTES = 72

# 字符类要求：≥ 3 of {小写 / 大写 / 数字 / 符号}。
# 低于此值意味着「几乎全字母」或「几乎全数字」，熵过低。
# 4 类齐备最佳，但不强求——避免手工输入过严变成噪音拒。
_CHARSET_LOWER = "abcdefghijklmnopqrstuvwxyz"
_CHARSET_UPPER = _CHARSET_LOWER.upper()
_CHARSET_DIGIT = "0123456789"
# 符号放宽：常见键盘可输入字符集，其它字符（中文 / 表情）若任意一类组合
# 已有 ≥ 3 类，仍允许——国际化友好。
_CHARSET_SYMBOL = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ \t")


# Aliased: legacy classes keep working under `except PasswordTooShortError` /
# `except WeakPasswordError` etc. (e.g. tests/unit/test_password_policy.py).
WeakPasswordError = I18nError
PasswordTooShortError = I18nError
PasswordTooLongError = I18nError


def _char_class_count(password: str) -> int:
    """统计密码命中的字符类数（最多 5：4 ASCII 类 + 1「非 ASCII」类）。

    非 ASCII（中文 / 日文 / 韩文 / 表情 / 数学符号等 Unicode 字符）单独计 1 类——
    Unicode 字符表空间远大于 ASCII 四类，单字符的信息熵已相当于 ASCII 7+ bit，
    一个中文段落同等长度的熵远高于 ASCII 全字母串。不单独成类会让 CJK 用户
    无法注册（必须手动插一个数字/符号），与「按熵拦截」的初衷相违。
    """
    has_lower = has_upper = has_digit = has_symbol = has_nonascii = False
    for ch in password:
        if ch in _CHARSET_LOWER:
            has_lower = True
        elif ch in _CHARSET_UPPER:
            has_upper = True
        elif ch in _CHARSET_DIGIT:
            has_digit = True
        elif ch in _CHARSET_SYMBOL:
            has_symbol = True
        elif ord(ch) > 127:
            has_nonascii = True
    return sum([has_lower, has_upper, has_digit, has_symbol, has_nonascii])


def validate_password_strength(password: str) -> None:
    """校验密码强度。失败抛 I18nError（http_status=400）。

    规则：
    1. 长度 ≥ MIN_LENGTH（12）
    2. ≥ 3 of {小写, 大写, 数字, 符号}
    3. UTF-8 字节数 ≤ _BCRYPT_MAX_BYTES（72）
    4. 不在弱密码表中（不区分大小写）
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
    if _char_class_count(password) < 3:
        # 字符类不足与命中黑名单语义不同：前者是「形态不达标」后者是「词典命中」，
        # 各自给独立文案而非共用 count 占位——共用会让 admin / 用户以为黑名单命中 N 条，
        # 实际是字符类不足，导致排查方向跑偏。
        raise I18nError(Keys.PASSWORD_CHARSET_INSUFFICIENT, http_status=400)
    if password.lower() in _WEAK_PASSWORDS:
        raise I18nError(
            Keys.PASSWORD_TOO_WEAK, http_status=400,
            count=len(_WEAK_PASSWORDS),
        )

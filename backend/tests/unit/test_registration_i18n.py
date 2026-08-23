"""注册流程相关 I18n Keys 存在性 + locale 文案到位。"""
from app.core.i18n.messages import Keys


def test_required_auth_keys_exist():
    for name in [
        "AUTH_USERNAME_INVALID_FORMAT",
        "AUTH_USERNAME_TAKEN",
        "AUTH_PASSWORD_MISMATCH",
        "AUTH_REGISTRATION_DISABLED",
        "AUTH_USER_NOT_FOUND",
    ]:
        assert hasattr(Keys, name), f"missing Keys.{name}"
        assert getattr(Keys, name).value == f"auth.{name.split('_', 1)[1].lower()}"


def test_config_invalid_bool_key_exists():
    assert hasattr(Keys, "CONFIG_INVALID_BOOL")
    assert Keys.CONFIG_INVALID_BOOL.value == "config.invalid_bool"

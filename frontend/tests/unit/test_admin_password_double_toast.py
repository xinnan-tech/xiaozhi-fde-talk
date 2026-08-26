"""改密双 toast bug：view catch 不再独立 toast 后端错误。

历史 bug：用户报告 issue #62——admin 改普通用户密码，弱密码时弹出**两条**提示。
根因：全局 http 响应拦截器（utils/http/index.ts:134-146）已对 4xx/5xx 自动 toast，
view 的 catch 又独立 message(extractBackendError(...))，两条同时弹出。

修法：view catch 只在「无 response 的网络错误」兜底——后端错误交还全局拦截器统一处理。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADMIN_USERS_VUE = ROOT / "src" / "views" / "admin" / "users" / "index.vue"
CHANGE_PWD_VUE = ROOT / "src" / "components" / "auth" / "ChangePasswordDialog.vue"


def _script_block(text: str) -> str:
    """提取 <script setup> 块内容（用于独立检查 submitReset catch）。"""
    start = text.index("<script")
    end = text.index("</script>", start)
    return text[start:end]


def test_admin_users_catch_no_longer_toasts_backend_detail():
    """admin/users/index.vue submitReset catch 不再独立 message(extractBackendError(...))。

    旧 bug：view catch 直接 message() → 与全局 http 拦截器重复 toast 两次。
    新行为：catch 仅在网络层异常（无 response）时给兜底，业务 4xx/5xx 交全局拦截器。
    """
    text = ADMIN_USERS_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    # 旧的「view catch 独立 toast 后端 detail」写法不应再出现
    assert "extractBackendError(e, t(\"users.reset_password_failed\"))" not in script, (
        "admin/users/index.vue 还在 catch 里 message(extractBackendError(...))——"
        "会与全局 http 拦截器形成双 toast（issue #62）"
    )
    # 网络兜底应保留（无 response 时全局拦截器不 toast）
    assert "users.reset_password_failed" in script, (
        "网络错误兜底文案应保留——全局拦截器只处理有 response 的情况"
    )


def test_admin_users_catch_guards_on_has_response():
    """view catch 必须用 hasResponse 守卫：只有无 response 时才 toast。"""
    text = ADMIN_USERS_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    assert "hasResponse" in script, (
        "view catch 应通过 hasResponse 判断是否需要兜底 toast"
    )
    # 守卫应该把 message() 包在 if 块里（粗略断言：catch 体内有 hasResponse 关键字）
    assert "if (!hasResponse)" in script, (
        "应只在 !hasResponse 时才 message()，避免与全局拦截器重复"
    )


def test_change_password_dialog_catch_no_longer_toasts_backend_detail():
    """ChangePasswordDialog submit catch 同样修：不再独立 toast 后端 detail。"""
    text = CHANGE_PWD_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    assert "extractBackendError(e, t(\"auth.change_password_failed\"))" not in script, (
        "ChangePasswordDialog 还在 catch 里 message(extractBackendError(...))——"
        "会与全局 http 拦截器形成双 toast（issue #62 同源反馈）"
    )
    # 网络兜底应保留
    assert "auth.change_password_failed" in text, (
        "网络错误兜底文案应保留"
    )


def test_change_password_dialog_catch_guards_on_has_response():
    """ChangePasswordDialog catch 也用 hasResponse 守卫。"""
    text = CHANGE_PWD_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    assert "hasResponse" in script
    assert "if (!hasResponse)" in script


def test_no_extract_backend_error_import_left():
    """两个文件不应再 import extractBackendError（已不再使用）。

    留着会触发 ESLint unused-import 警告；TS 项目会编译报错。
    """
    for path in (ADMIN_USERS_VUE, CHANGE_PWD_VUE):
        text = path.read_text(encoding="utf-8")
        assert "import { extractBackendError }" not in text, (
            f"{path.name} 已不再使用 extractBackendError，但 import 还在"
        )


def test_global_http_interceptor_still_toasts_on_4xx():
    """全局拦截器对 4xx 的 toast 不能动——这是双 toast 修法的依赖方。

    修 view 层的逻辑前提是「全局拦截器仍兜底」，删 view toast 之前
    必须先确认全局行为没被这次改动误伤。
    """
    interceptor = (ROOT / "src" / "utils" / "http" / "index.ts").read_text(encoding="utf-8")
    assert "extractDetailText(responseBody?.detail)" in interceptor
    assert "grouping: true" in interceptor, (
        "全局拦截器的 grouping:true 必须保留——本测试断言它没被误删"
    )
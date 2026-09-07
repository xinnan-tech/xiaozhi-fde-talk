"""system saveConfig + 同源 view catch 不再独立 toast 后端 detail。

issue #177 反馈：ASR 保存留空 api_key，弹出**两条**提示：
  - 「asr.doubao_stream.api_key 为必填项，请填写后保存」（拦截器）
  - 「保存 语音识别 配置失败：asr.doubao_stream.api_key 为必填项，请填写后保存」（view catch）

根因：全局 http 响应拦截器已对 4xx/5xx 自动 toast，view catch 又独立
ElMessage.error(extractBackendError(...))，两条同时弹出。修复方式与 #62
一致：view catch 只在「无 response 的网络错误」时给兜底，业务错误交拦截器。

修法扩展到 system / interview / create-dialog / app 共 9 处 catch：
- system saveConfig（用户报的 bug）
- system runSelfCheck
- interview resume / pause / end
- create-dialog clipboard / voice / ocr × 2
- app create interview
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_VUE = ROOT / "src" / "views" / "system" / "index.vue"
INTERVIEW_VUE = ROOT / "src" / "views" / "interview" / "index.vue"
CREATE_DIALOG_VUE = ROOT / "src" / "components" / "interview" / "CreateInterviewDialog.vue"
APP_VUE = ROOT / "src" / "App.vue"
ZH_CN_LOCALE = ROOT / "src" / "locales" / "zh-CN.json"
EN_US_LOCALE = ROOT / "src" / "locales" / "en-US.json"


def _script_block(text: str) -> str:
    start = text.index("<script")
    end = text.index("</script>", start)
    return text[start:end]


# ── system/index.vue saveConfig ────────────────────────────────────────────────


def test_system_save_config_catch_uses_has_response_guard():
    """saveConfig catch 必须用 hasResponse 守卫：只有无 response 时才 toast。"""
    script = _script_block(SYSTEM_VUE.read_text(encoding="utf-8"))
    assert "hasResponse" in script
    assert "if (!hasResponse)" in script


def test_system_save_config_catch_no_longer_toasts_backend_detail_inline():
    """saveConfig catch 不再用内联 ElMessage.error(extractBackendError(...))。

    旧 bug：catch 直接 ElMessage.error → 与全局 http 拦截器重复 toast 两次。
    新行为：catch 仅在网络层异常（无 response）时给兜底，业务 4xx/5xx 交拦截器。
    """
    script = _script_block(SYSTEM_VUE.read_text(encoding="utf-8"))
    # 旧写法：t("system.save_failed", { ..., message: getErrorMessage(err) })
    assert "message: getErrorMessage(err)" not in script, (
        "saveConfig catch 还在用 getErrorMessage(err) 作 toast 详情——"
        "与全局 http 拦截器形成双 toast（issue #177）"
    )


def test_system_save_failed_network_locale_exists():
    """网络兜底用独立 i18n key system.save_failed_network。

    原本 system.save_failed 模板带 {message} 占位（与 detail 拼接），网络
    兜底没有 detail 可拼接——新增 system.save_failed_network 不带占位。
    """
    import json

    for path in (ZH_CN_LOCALE, EN_US_LOCALE):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "system.save_failed_network" in data, (
            f"{path.name} 缺少 system.save_failed_network 网络兜底文案"
        )
        # 必须以 group 占位结尾的友好文案（无 message 占位，否则又走老路）
        text = data["system.save_failed_network"]
        assert "{message}" not in text, (
            f"system.save_failed_network 不应再有 {{message}} 占位：{text!r}"
        )


def test_system_save_failed_locale_unchanged():
    """原 system.save_failed 模板仍保留（saveConfig 的 else 分支和别处仍在用）。

    修法：catch 改用新 key；其它场景（res.ok === false 兜底）继续用旧 key。
    """
    import json

    for path in (ZH_CN_LOCALE, EN_US_LOCALE):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "system.save_failed" in data
        assert "{message}" in data["system.save_failed"], (
            f"{path.name} 不应误删 system.save_failed 的 {{message}} 占位"
        )


# ── system/index.vue runSelfCheck ──────────────────────────────────────────────


def test_system_run_self_check_catch_uses_has_response_guard():
    """runSelfCheck catch 同样用 hasResponse 守卫（详情仍写入 UI 卡片）。"""
    script = _script_block(SYSTEM_VUE.read_text(encoding="utf-8"))
    # runSelfCheck 与 saveConfig 共用 hasResponse 守卫模式
    assert script.count("hasResponse") >= 2, (
        "system/index.vue 至少应有 saveConfig + runSelfCheck 两处 hasResponse 守卫"
    )


# ── interview/index.vue ────────────────────────────────────────────────────────


def test_interview_resume_catch_uses_has_response_guard():
    """interview resume catch 改 hasResponse 守卫。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    assert "interview.resume_failed" in script, (
        "i18n key 仍应保留（网络兜底文案）"
    )
    # 原写法 extractBackendError(e, t("interview.resume_failed")) 应被替换
    assert "extractBackendError(e, t(\"interview.resume_failed\"))" not in script
    assert "hasResponse" in script


def test_interview_pause_catch_uses_has_response_guard():
    """interview pause catch 改 hasResponse 守卫。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    assert "interview.pause_failed" in script
    assert "extractBackendError(e, t(\"interview.pause_failed\"))" not in script


def test_interview_end_catch_uses_has_response_guard():
    """interview end catch 也改 hasResponse 守卫（详见 test_double_toast_extension）。

    原本 test_double_toast_extension 说 end 是「网络兜底，不修」，但同源 bug
    一样存在（拦截器对 4xx/5xx 也 toast），新测试锁死它也走守卫。
    """
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    assert "interview.end_failed" in script
    assert "extractBackendError(e, t(\"interview.end_failed\"))" not in script


def test_interview_no_extract_backend_error_import():
    """interview/index.vue 已不再使用 extractBackendError，import 也要清掉。"""
    text = INTERVIEW_VUE.read_text(encoding="utf-8")
    assert "import { extractBackendError }" not in text, (
        "interview/index.vue 已不再使用 extractBackendError，但 import 还在"
    )


# ── CreateInterviewDialog.vue ─────────────────────────────────────────────────


def test_create_dialog_clipboard_catch_uses_has_response_guard():
    """CreateInterviewDialog clipboard catch 改 hasResponse 守卫。"""
    script = _script_block(CREATE_DIALOG_VUE.read_text(encoding="utf-8"))
    assert "hasResponse" in script
    assert "if (!hasResponse)" in script
    # clipboard 旧写法：extractBackendError(error, t("create.dialog.clipboard_failed"))
    assert "extractBackendError(error, t(\"create.dialog.clipboard_failed\"))" not in script


def test_create_dialog_voice_catch_uses_has_response_guard():
    """CreateInterviewDialog voice catch 改 hasResponse 守卫。"""
    script = _script_block(CREATE_DIALOG_VUE.read_text(encoding="utf-8"))
    assert "extractBackendError(error, t(\"create.dialog.voice_failed\"))" not in script


def test_create_dialog_ocr_catch_uses_has_response_guard():
    """CreateInterviewDialog OCR catch（拍照+裁剪两处）都改 hasResponse 守卫。"""
    script = _script_block(CREATE_DIALOG_VUE.read_text(encoding="utf-8"))
    # 拍照 OCR
    assert "extractBackendError(error, t(\"create.dialog.ocr_failed\"))" not in script
    # 裁剪 OCR
    assert "extractBackendError(error, t(\"create.dialog.upload_failed\"))" in script, (
        "blobToBase64 / snapCamera 是客户端 composable（非 HTTP），"
        "那一处 extractBackendError 必须保留——不能误删"
    )


def test_create_dialog_keeps_extract_backend_error_for_client_errors():
    """snapCamera / blobToBase64 是客户端 composable（非 HTTP），保留 extractBackendError。

    客户端错误（canvas getContext null / FileReader fail）拦截器不处理，
    必须由 view 用 extractBackendError 兜底——这条不能动。
    """
    text = CREATE_DIALOG_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    # snapCamera 在拍照 click handler 内（line ~680）——客户端错误，应保留
    assert "extractBackendError(error, t(\"create.dialog.camera_unavailable\"))" in script
    # blobToBase64 在文件选择 handler 内（line ~784）——客户端错误，应保留
    assert "extractBackendError(error, t(\"create.dialog.upload_failed\"))" in script


# ── App.vue createInterview ────────────────────────────────────────────────────


def test_app_create_interview_catch_uses_has_response_guard():
    """App.vue createInterview catch 改 hasResponse 守卫。

    旧 bug：catch 直接拿 detail toast——与拦截器双 toast。
    新行为：catch 仅在网络层异常（无 response）时给兜底。
    """
    text = APP_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    assert "hasResponse" in script
    assert "if (!hasResponse)" in script
    # 旧写法：typeof detail === "string" ? detail : t("app.interview_create_failed")
    assert "typeof detail === \"string\"" not in script, (
        "App.vue createInterview catch 不应再内联拿 detail——"
        "会与全局拦截器形成双 toast"
    )


# ── 全局 http 拦截器仍然 toast（所有修法都依赖它）─────────────────────────────


def test_global_http_interceptor_still_toasts_on_4xx():
    """全局拦截器对 4xx 的 toast 不能动——本轮所有修复都依赖它兜底。

    修 view 层的前提是「全局拦截器仍兜底」。删 view toast 之前
    必须先确认全局行为没被本次扩展误伤。
    """
    interceptor = (ROOT / "src" / "utils" / "http" / "index.ts").read_text(encoding="utf-8")
    assert "extractDetailText(responseBody?.detail)" in interceptor
    assert "grouping: true" in interceptor

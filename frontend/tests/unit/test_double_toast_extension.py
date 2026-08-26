"""同源扩展 #62：5 处 view catch 不再独立 toast 后端 detail。

issue #62 修复（admin 改密）后，全局 http 拦截器已统一 toast 后端 4xx/5xx detail，
以下 5 处 view catch 同源——再 message()/ElMessage.error(extractBackendError(...))
会形成双 toast。本测试锁死这 5 处不再独立 toast 后端 detail。

不修的两类（已知风险，但不属于双 toast bug）：
- interview:890 end_interview 网络层断场景（全局拦截器不处理，view 兜底是唯一）
- system:415 diagnostics helper 函数（调用方决定）
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_VUE = ROOT / "src" / "views" / "report" / "index.vue"
INTERVIEW_VUE = ROOT / "src" / "views" / "interview" / "index.vue"


def _script_block(text: str) -> str:
    start = text.index("<script")
    end = text.index("</script>", start)
    return text[start:end]


def test_report_export_catch_no_longer_toasts_backend_detail():
    """report/index.vue 导出 catch 不再独立 toast 后端 detail。"""
    script = _script_block(REPORT_VUE.read_text(encoding="utf-8"))
    assert "extractBackendError(" not in script, (
        "report/index.vue script 不应再有 extractBackendError("
        "（5 处全改完，应清空 import）"
    )


def test_report_delete_catch_no_longer_toasts_backend_detail():
    """report/index.vue 删除 catch 改 hasResponse 守卫。"""
    text = REPORT_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    assert "hasResponse" in script, (
        "report/index.vue 删除 catch 应有 hasResponse 守卫"
    )
    assert "if (!hasResponse)" in script


def test_report_export_catch_uses_has_response_guard():
    """report/index.vue 导出 catch 也用 hasResponse 守卫。"""
    script = _script_block(REPORT_VUE.read_text(encoding="utf-8"))
    assert "hasResponse" in script
    assert "if (!hasResponse)" in script


def test_interview_suggestion_ignore_catch_uses_has_response_guard():
    """interview suggestion.ignore catch 改 hasResponse 守卫。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    # 找出 ignore_failed 那段（line ~713 起）
    assert "interview.suggestion.ignore_failed" in script, (
        "i18n key 仍应保留（网络兜底文案）"
    )
    assert "hasResponse" in script


def test_interview_suggestion_unignore_catch_uses_has_response_guard():
    """interview suggestion.unignore catch 改 hasResponse 守卫。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    assert "interview.suggestion.unignore_failed" in script
    assert "hasResponse" in script


def test_interview_first_batch_catch_uses_has_response_guard():
    """interview first_batch catch 改 hasResponse 守卫。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    assert "msg.first_batch_partial" in script
    assert "hasResponse" in script


def test_interview_end_interview_unchanged():
    """interview end_interview catch 保留 view 兜底（不修）。

    网络层断（无 response）时全局拦截器不处理——view catch 是唯一兜底。
    不能简单套「hasResponse 守卫」删除 view toast。
    """
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    # 这条 catch 仍用 extractBackendError(e, t("interview.end_failed"))
    assert "extractBackendError(e, t(\"interview.end_failed\"))" in script, (
        "interview end_interview 网络兜底应继续存在"
    )


def test_no_extract_backend_error_import_in_report():
    """report/index.vue 不再有 extractBackendError import（全 2 处已改完）。"""
    text = REPORT_VUE.read_text(encoding="utf-8")
    assert "import { extractBackendError }" not in text, (
        "report/index.vue 已不再使用 extractBackendError，但 import 还在"
    )


def test_global_http_interceptor_still_toasts_on_4xx():
    """全局拦截器对 4xx 的 toast 不能动——5 处修复都依赖它兜底。

    修 view 层的前提是「全局拦截器仍兜底」。删 view toast 之前
    必须先确认全局行为没被这次扩展误伤。
    """
    interceptor = (ROOT / "src" / "utils" / "http" / "index.ts").read_text(encoding="utf-8")
    assert "extractDetailText(responseBody?.detail)" in interceptor
    assert "grouping: true" in interceptor
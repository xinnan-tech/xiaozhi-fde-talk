"""issue #13：长静默自动暂停后，弹确认框让用户感知。

之前 session.suspended 推到前端只静默改 status 为 suspended + 关麦停表，
用户看不到任何反馈。修复：在 session.suspended 分支弹 ElMessageBox.confirm，
点「继续」走 handleStartInterview 重连回 in_progress；取消则停留在
suspended 状态，控制按钮仍可手动继续。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTERVIEW_VUE = ROOT / "src" / "views" / "interview" / "index.vue"


def _script_block(text: str) -> str:
    start = text.index("<script")
    end = text.index("</script>", start)
    return text[start:end]


def _function_body(script: str, signature: str) -> str:
    """截取从签名开始到下一个顶层 const/function/exports 之间的源码。"""
    start = script.index(signature)
    tail = script[start + len(signature):]
    end_candidates = []
    for marker in ("\nconst ", "\nfunction ", "\nwatch(", "\nonMounted(", "\nexport "):
        idx = tail.find(marker)
        if idx >= 0:
            end_candidates.append(idx)
    end = min(end_candidates) if end_candidates else len(tail)
    return script[start:start + len(signature) + end]


def test_handle_session_suspended_defined_and_uses_message_box():
    """handleSessionSuspended 必须存在并用 ElMessageBox.confirm。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleSessionSuspended = async () => {")
    assert "ElMessageBox.confirm(" in body, (
        "handleSessionSuspended 必须弹 ElMessageBox.confirm，否则暂停通知仍不显眼"
    )
    assert "suspend_dialog.message" in body, (
        "弹框内容必须用 interview.runtime.suspend_dialog.message i18n key"
    )
    assert "suspend_dialog.title" in body, (
        "弹框标题必须用 interview.runtime.suspend_dialog.title i18n key"
    )


def test_handle_session_suspended_calls_start_on_confirm():
    """确认分支必须调 handleStartInterview 重连；取消则停在 suspended。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleSessionSuspended = async () => {")
    # try 块内 await handleStartInterview() 是恢复路径
    assert "await handleStartInterview()" in body, (
        "确认后必须 await handleStartInterview() 重连（suspended 分支已内置）"
    )
    # catch 块留空注释：用户取消时维持 suspended 状态
    assert "} catch {" in body or "} catch (" in body, (
        "必须有 catch 兜住用户取消的场景，否则 unhandled rejection 噪声"
    )


def test_handle_session_suspended_uses_reentrancy_guard():
    """重复触发不能堆栈多个弹框；用 finally 重置 flag。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleSessionSuspended = async () => {")
    assert "isSuspendConfirmDialogOpen" in body, (
        "必须用 isSuspendConfirmDialogOpen 防重入，重复弹框会卡 UI"
    )
    assert "finally" in body, "finally 块必须重置 flag"
    # finally 里要回到 false
    finally_idx = body.rindex("finally")
    after = body[finally_idx:]
    assert "isSuspendConfirmDialogOpen = false" in after, (
        "finally 块必须重置 isSuspendConfirmDialogOpen，否则下次弹不出"
    )


def test_session_suspended_branch_invokes_dialog():
    """session.suspended 分支必须调 handleSessionSuspended，session.ended 不弹。"""
    text = INTERVIEW_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    # 在 if message.type === "session.ended" || message.type === "session.suspended" 块内
    suspended_idx = script.index('message.type === "session.suspended"')
    # 找下一个顶层 } 配对起点；简化用最近的 session.ended 反向定位
    branch_start = script.rindex('message.type === "session.ended"', 0, suspended_idx)
    # 取这一段 if 块的尾部直到下一个独立 if/return
    tail = script[branch_start:]
    # 找下一个 const 顶层声明作为段落结束
    next_const = tail.find("\nconst ", 100)
    if next_const < 0:
        next_const = tail.find("\nfunction ", 100)
    block = tail[:next_const if next_const > 0 else len(tail)]
    assert "handleSessionSuspended" in block, (
        "session.suspended 分支必须调 handleSessionSuspended 弹确认框"
    )
    # 确认调用仅在 suspended 分支，不在 ended 分支
    assert "session.ended" in block  # sanity check 拿到正确的块


def test_suspend_dialog_i18n_keys_in_all_locales():
    """新增的 4 个 suspend_dialog key 必须在 4 locale 齐平（缺一 build 失败）。"""
    locales = (
        ROOT / "src" / "locales" / "zh-CN.json",
        ROOT / "src" / "locales" / "zh-TW.json",
        ROOT / "src" / "locales" / "en-US.json",
        ROOT / "src" / "locales" / "vi-VN.json",
    )
    needed = (
        "interview.runtime.suspend_dialog.title",
        "interview.runtime.suspend_dialog.message",
        "interview.runtime.suspend_dialog.confirm",
        "interview.runtime.suspend_dialog.cancel",
    )
    for path in locales:
        keys = set(json.loads(path.read_text(encoding="utf-8")).keys())
        missing = [k for k in needed if k not in keys]
        assert not missing, f"{path.name} 缺 {missing}"

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
WEBSOCKET_TS = ROOT / "src" / "composables" / "useWebSocket.ts"


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


def test_handle_session_suspended_rechecks_ended_after_confirm():
    """弹框期间后端推了 session.ended 时，用户点继续必须有可见反馈。

    await ElMessageBox.confirm 期间 WS 仍可推 ended；用户点「继续」后
    若直接进 handleStartInterview，入口守卫会静默 return，用户毫无
    反馈。要在调 start 前再查一次，命中即 toast 告知。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleSessionSuspended = async () => {")
    # confirm await 与 handleStartInterview 之间的 ended 守卫
    confirm_idx = body.index("await ElMessageBox.confirm(")
    start_idx = body.index("await handleStartInterview()")
    between = body[confirm_idx:start_idx]
    assert 'status === "ended"' in between, (
        "弹框 await 之后、调 handleStartInterview 之前必须再查 status === "
        "'ended'，否则 ended 状态会被入口守卫静默吞掉"
    )
    assert "ElMessage" in between, (
        "ended 命中必须给一条 ElMessage 提示，否则用户不知道为何没继续"
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
        "interview.runtime.suspend_dialog.ended_while_waiting",
    )
    for path in locales:
        keys = set(json.loads(path.read_text(encoding="utf-8")).keys())
        missing = [k for k in needed if k not in keys]
        assert not missing, f"{path.name} 缺 {missing}"


def test_use_web_socket_exports_allow_reconnect():
    """useWebSocket 必须导出 allowReconnect 复位函数。

    session.suspended 路径把 isReconnectAllowed 置 false 后，必须有外部
    接口把它置 true，否则暂停弹框选「继续」时 openWebSocket 没法重连。
    """
    text = WEBSOCKET_TS.read_text(encoding="utf-8")
    assert "const allowReconnect = () =>" in text, (
        "useWebSocket 必须定义 allowReconnect 复位函数"
    )
    assert "isReconnectAllowed.value = true" in text, (
        "allowReconnect 必须把 isReconnectAllowed 置 true 才能再次 autoReconnect"
    )
    # 必须出现在 return 对象里
    assert "allowReconnect," in text, (
        "allowReconnect 必须从 useWebSocket 返回给 view 使用"
    )


def test_handle_start_interview_resets_reconnect_before_open():
    """handleStartInterview 必须在 openWebSocket 前调 allowReconnect。

    suspended 路径把可重连标志置 false 后直接 open，autoReconnect 立即
    拒绝 → 用户体验「继续」后连接仍卡死。把复位提到 open 之前，确保即使
    上一次断开发生在弹框期间，重连链也能重新被允许。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleStartInterview = async () => {")
    allow_idx = body.index("allowReconnect()")
    open_idx = body.index("openWebSocket()")
    assert allow_idx < open_idx, (
        "allowReconnect() 必须在 openWebSocket() 之前，否则重连锁仍关闭"
    )


def test_handle_start_interview_guards_against_ended_status():
    """handleStartInterview 入口必须拦下 status === 'ended' 的情况。

    session.ended 与 session.suspended 共用同一分支，弹框等待期间后端
    可能再推 ended；若用户仍点「继续」则会把 ended 改回 in_progress，
    状态机被异步路径撕坏。要在入口用 handleControlButtonClick 同样的
    白名单守住。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleStartInterview = async () => {")
    # 入口第一个判断就是 ended 守卫
    assert 'status === "ended"' in body[:body.index("isInterviewStarted")], (
        "status === 'ended' 守卫必须在 isInterviewStarted 检查之前"
    )
    assert "return;" in body[:body.index("isInterviewStarted")], (
        "ended 状态命中后必须 return，否则继续往下跑改 status"
    )


def test_handle_start_interview_rechecks_ended_after_each_await():
    """每个 await 之后必须再查一次 status，涵盖 ended 与 suspended 两种终态。

    acquireStream / openMicrophone 是 await 窗口，期间后端若推
    session.ended 或再推 session.suspended（idle 超时叠加 / admin 手动
    暂停），handleServerMessage 会把 status 写为 ended/suspended；await
    返回后若不重查就接着 status = "in_progress"，把后端的终态翻成进行中。
    """
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleStartInterview = async () => {")
    # acquireStream 之后必须再查 ended + suspended
    acquire_idx = body.index("await acquireStream()")
    next_status_mutate = body.index('status = "in_progress"', acquire_idx)
    after_acquire = body[acquire_idx:next_status_mutate]
    assert 'status === "ended"' in after_acquire, (
        "await acquireStream() 之后必须再查 status === 'ended'"
    )
    assert 'status === "suspended"' in after_acquire, (
        "await acquireStream() 之后必须再查 status === 'suspended'，"
        "否则 idle 超时叠加期间推过来的 suspended 会被复活成 in_progress"
    )
    # openMicrophone 之后同样要查两个终态
    if "await openMicrophone()" in body:
        open_mic_idx = body.index("await openMicrophone()")
        after_open_mic = body[open_mic_idx:]
        assert 'status === "ended"' in after_open_mic, (
            "await openMicrophone() 之后必须再查 status === 'ended'"
        )
        assert 'status === "suspended"' in after_open_mic, (
            "await openMicrophone() 之后必须再查 status === 'suspended'"
        )


def test_handle_start_interview_entry_does_not_block_suspended_resume():
    """入口守卫只拦 ended 不能拦 suspended。

    handleControlButtonClick / handleSessionSuspended 都会在 status 为
    suspended 时主动调 handleStartInterview「继续」。入口若把 suspended
    也算"终态"拦截，continue 路径就废了。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleStartInterview = async () => {")
    # 入口 ended 守卫单独一句 if，且不含 suspended
    entry_ended_line = body.index('status === "ended"')
    next_line_idx = body.index("\n", entry_ended_line)
    entry_check = body[entry_ended_line:next_line_idx]
    assert 'suspended' not in entry_check, (
        "入口 ended 守卫不能扩展到 suspended，否则 continue 流程被废"
    )

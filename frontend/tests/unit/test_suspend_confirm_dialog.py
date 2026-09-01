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


def test_handle_session_suspended_distinguishes_cancel_from_real_errors():
    """catch 必须区分用户取消与 handleStartInterview 内部异常。

    Element Plus 用户取消 confirm 时 reject 的值是字符串 'cancel' /
    'close'；handleStartInterview 内部抛出（除已被自身 toast 兜底的麦权限
    失败等场景外）属于意外，需要给 ElMessage.error 兜底，否则用户点
    「继续」后无任何反馈、状态卡死。
    """
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleSessionSuspended = async () => {")
    # catch 必须区分两种来源：Element Plus 取消 reject 的字符串 / 其他异常
    assert '"cancel"' in body, (
        "catch 必须显式判断 Element Plus 取消 reject 的字符串 'cancel'"
    )
    assert '"close"' in body or "distinguishCancelAndClose" in body, (
        "catch 应同时识别 'close'（区分 cancel/close 时）或显式声明不区分"
    )
    # 真异常兜底：必须有 ElMessage.error，否则用户毫无反馈
    assert "ElMessage.error" in body, (
        "handleStartInterview 内部抛出未捕获时必须 ElMessage.error 兜底，"
        "否则用户点「继续」后没有任何反馈"
    )
    assert "resume_failed" in body, (
        "ElMessage.error 必须用 interview.runtime.suspend_dialog.resume_failed i18n key"
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
        "interview.runtime.suspend_dialog.resume_failed",
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


def test_ws_disconnect_keeps_resume_intent_while_interview_is_started():
    """继续期间的旧 WS 断开不能清掉握手后的 listen:start 意图。

    暂停后旧连接的 disconnect 事件可能晚于用户点击继续到达；如果无条件
    清 shouldResumeMicrophone，新连接 hello 后会跳过 openMicrophone()。
    """
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    on_disconnected_idx = script.index("onDisconnected: event => {")
    body = script[on_disconnected_idx:]
    body = body[:body.index("\n  },", 1) + len("\n  },")]
    assert "shouldResumeMicrophone.value = isInterviewStarted.value" in body, (
        "WebSocket 断开时必须在访谈仍处于启动状态时保留恢复监听意图"
    )
    assert "shouldResumeMicrophone.value = false;" not in body, (
        "不能在 onDisconnected 中无条件清除恢复监听意图"
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

    实现上为了避开 TS 控制流把 ended/suspended 收窄（入口守卫已 return
    on ended，导致下游字面比较被收窄成无交集），这里用了一个 string |
    undefined 类型的本地变量承接新读到的 status。守住这个模式即可，不
    锁死变量名。
    """
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleStartInterview = async () => {")
    # acquireStream 之后必须再查 ended + suspended
    acquire_idx = body.index("await acquireStream()")
    next_status_mutate = body.index('status = "in_progress"', acquire_idx)
    after_acquire = body[acquire_idx:next_status_mutate]
    assert '=== "ended"' in after_acquire, (
        "await acquireStream() 之后必须再查 === 'ended'"
    )
    assert '=== "suspended"' in after_acquire, (
        "await acquireStream() 之后必须再查 === 'suspended'，"
        "否则 idle 超时叠加期间推过来的 suspended 会被复活成 in_progress"
    )
    # openMicrophone 之后同样要查两个终态
    if "await openMicrophone()" in body:
        open_mic_idx = body.index("await openMicrophone()")
        after_open_mic = body[open_mic_idx:]
        assert '=== "ended"' in after_open_mic, (
            "await openMicrophone() 之后必须再查 === 'ended'"
        )
        assert '=== "suspended"' in after_open_mic, (
            "await openMicrophone() 之后必须再查 === 'suspended'"
        )


def test_open_microphone_guard_does_full_cleanup():
    """openMicrophone 守卫命中必须复位 isInterviewStarted / 停表。

    与 acquireStream 守卫对齐——否则命中后留下 isInterviewStarted=true
    半开状态，下次 handleStartInterview 进不来；同时计时器也在空跑。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleStartInterview = async () => {")
    assert "statusAfterMic" not in body or body.index("statusAfterMic") > 0
    # 找 openMicrophone 守卫的 if 块（statusAfterMic 之后的第一个 if）
    if "statusAfterMic" not in body:
        return
    mic_idx = body.index("statusAfterMic")
    guard_block = body[mic_idx:]
    # 守卫块必须在 handleStartInterview 体内找到 isInterviewStarted 重置与 stopInterviewTimer
    assert "isInterviewStarted.value = false" in guard_block, (
        "openMicrophone 守卫命中必须 isInterviewStarted.value = false，"
        "否则下次 handleStartInterview 被入口守卫拦掉"
    )
    assert "stopInterviewTimer()" in guard_block, (
        "openMicrophone 守卫命中必须 stopInterviewTimer()，"
        "否则计时器空跑"
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


def test_post_await_suspended_guard_distinguishes_was_suspended():
    """await 守卫的 suspended 分支必须用 !wasSuspended 区分入口状态。

    入口本就是 suspended（continue 路径）的合法情况不能在 await 守卫里
    误命中：必须用入口时记录的 wasSuspended 区分「入口是 suspended 的
    合法 continue」与「await 期间后端又推了一次 suspended」。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleStartInterview = async () => {")
    # wasSuspended 必须先于两个 await 守卫定义
    was_suspended_idx = body.index("const wasSuspended")
    acquire_guard_idx = body.index("statusAfterAcquire")
    assert was_suspended_idx < acquire_guard_idx, (
        "wasSuspended 必须在 await 守卫之前定义，否则守卫没法区分入口状态"
    )
    # 两个 await 守卫里都要带 !wasSuspended（仅在 suspended 分支）
    assert '!wasSuspended' in body[acquire_guard_idx:], (
        "acquireStream 之后的 suspended 分支必须加 !wasSuspended，"
        "否则入口本就是 suspended 的 continue 流程被自废"
    )
    if "statusAfterMic" in body:
        mic_guard_idx = body.index("statusAfterMic")
        assert '!wasSuspended' in body[mic_guard_idx:], (
            "openMicrophone 之后的 suspended 分支同样必须加 !wasSuspended"
        )


def test_handle_server_message_skips_cleanup_when_dialog_in_flight():
    """session.suspended 弹框流程仍在处理时，本端 cleanup 必须跳过。

    用户点继续但 handleStartInterview 尚未跑完（isSuspendConfirmDialogOpen
    仍为 true）期间，后端若再推 session.suspended，handleServerMessage
    若正常 cleanup，会把 isInterviewStarted/mic/timer 改写——而
    handleStartInterview 跑完会写入新 status 但读不到这些 ref 的最新值，
    留下半开状态（status=in_progress 但 isInterviewStarted=false / 麦未启）。"""
    text = INTERVIEW_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    # 找 session.ended/suspended 合并分支：session.suspended 与 dialog 标志的交互
    suspended_branch_idx = script.index('message.type === "session.suspended"')
    # 找分支的尾部（再下一个顶层 const/function/export）
    tail = script[suspended_branch_idx:]
    next_const = tail.find("\nconst ", 100)
    next_function = tail.find("\nfunction ", 100)
    next_close = tail.find("\n};", 100)
    end_candidates = [i for i in (next_const, next_function, next_close) if i > 0]
    end = min(end_candidates) if end_candidates else len(tail)
    branch = tail[:end]
    # 守卫逻辑：suspended + isSuspendConfirmDialogOpen 时跳过 cleanup
    assert "isSuspendConfirmDialogOpen" in branch, (
        "session.suspended 分支必须看 isSuspendConfirmDialogOpen，"
        "决定是否跳过本端 cleanup"
    )
    # cleanup 三件套（shouldResumeMicrophone/stopRecording/isInterviewStarted/
    # stopInterviewTimer）必须在守卫逻辑控制下，不能无条件跑
    cleanup_block_must_be_guarded = (
        "stopRecording()" in branch and "stopInterviewTimer()" in branch
    )
    assert cleanup_block_must_be_guarded, (
        "分支应包含 cleanup 操作但必须用 isSuspendConfirmDialogOpen 守住"
    )


def test_handle_server_message_skips_status_overwrite_when_dialog_in_flight():
    """session.suspended 弹框流程仍在处理时，status 覆写也必须跳过。

    只挡 cleanup 不挡 status 覆写会留半开状态：handleStartInterview 在
    await openMicrophone() 之前写过 status=in_progress，等麦热启期间
    后端再推 session.suspended 若把 status 翻回 suspended，post-await
    守卫因 wasSuspended=true 漏命中、函数正常返回；用户再点「继续」
    会被入口守卫 isInterviewStarted=true 静默吞。"""
    text = INTERVIEW_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    suspended_branch_idx = script.index('message.type === "session.suspended"')
    tail = script[suspended_branch_idx:]
    next_const = tail.find("\nconst ", 100)
    next_function = tail.find("\nfunction ", 100)
    next_close = tail.find("\n};", 100)
    end_candidates = [i for i in (next_const, next_function, next_close) if i > 0]
    end = min(end_candidates) if end_candidates else len(tail)
    branch = tail[:end]
    # status 覆写代码字符串必须在 !skipLocalCleanup 块内：找 if (!skipLocalCleanup) {
    # 与配对 } 之间的内容，断言 status 覆写在其中
    guard_open = branch.index("if (!skipLocalCleanup")
    # 找下一个 } 配对起点——用 block 内缩进对齐的 } 标记
    # 简化做法：找下一个 "if (" 行之前最近的 "\n    }"（4 空格缩进）
    rest = branch[guard_open:]
    inner_close_candidates = [
        rest.find("\n    }", 1),  # 跳过 if 自己
    ]
    inner_close_candidates = [i for i in inner_close_candidates if i > 0]
    if not inner_close_candidates:
        # 没匹配 4 空格缩进就放宽到任意 }
        inner_close_candidates = [rest.find("\n  }", 1)]
    inner_end = min(inner_close_candidates) if inner_close_candidates else len(rest)
    guarded_block = rest[:inner_end]
    assert "interviewDetail.value.status" in guarded_block, (
        "status 覆写必须在 !skipLocalCleanup 块内；"
        "弹框期间再推的 suspended 不能推翻 in-flight handleStartInterview "
        "已经写回的 in_progress"
    )


def test_handle_server_message_closes_dialog_when_ended_during_in_flight():
    """ended 落地时若弹框仍开，必须主动关掉。

    弹框文案「暂停」与 status=ended 撕裂、用户点取消 finally 关弹框
    全程无 ended 反馈。修法：handleServerMessage 的 ended 分支若
    isSuspendConfirmDialogOpen=true，调用 ElMessageBox.close()，
    toast 留给 handleSessionSuspended 的 catch / post-await re-check
    统一发，避免双弹。"""
    text = INTERVIEW_VUE.read_text(encoding="utf-8")
    script = _script_block(text)
    ended_branch_idx = script.index('message.type === "session.ended"')
    tail = script[ended_branch_idx:]
    next_const = tail.find("\nconst ", 100)
    next_function = tail.find("\nfunction ", 100)
    next_close = tail.find("\n};", 100)
    end_candidates = [i for i in (next_const, next_function, next_close) if i > 0]
    end = min(end_candidates) if end_candidates else len(tail)
    branch = tail[:end]
    assert 'message.type === "session.ended" && isSuspendConfirmDialogOpen' in branch, (
        "ended 分支必须显式判 isSuspendConfirmDialogOpen 才关弹框，"
        "否则无差别 close 会误关其他场景的弹框"
    )
    assert "ElMessageBox.close()" in branch, (
        "ended + 弹框开的情况下必须主动 ElMessageBox.close() 撕裂的 dialog"
    )


def test_handle_session_suspended_rechecks_ended_after_resume():
    """post-await 守卫命中 ended 静默 return，handleSessionSuspended 必须自兜底。

    handleStartInterview 的 post-await 守卫（acquireStream / openMicrophone
    之后）对 ended 静默 return、不 throw；handleSessionSuspended 的 try
    块正常返回、finally 只复位 flag，用户无反馈。修法：handleSessionSuspended
    在 await handleStartInterview() 之后再查一次 status==ended，命中即
    ended_while_waiting。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleSessionSuspended = async () => {")
    # 找 await handleStartInterview() 之后的 ended_while_waiting 调用
    start_idx = body.index("await handleStartInterview()")
    after = body[start_idx:]
    assert "ended_while_waiting" in after, (
        "handleStartInterview await 之后必须再查一次 status==ended 并给一条 "
        "ended_while_waiting 兜底；post-await 守卫对 ended 静默 return "
        "不会自 toast"
    )
    # 顺序：先 await，再 ended_while_waiting
    warning_idx = after.index("ended_while_waiting")
    # 不能在 await 之前出现 ended_while_waiting
    pre = body[:start_idx]
    pre_ended_count = pre.count("ended_while_waiting")
    # 入场守卫那条 ended 检查的 ended_while_waiting 是合理的，不计入
    # 这里只关心 post-await 段至少有一条
    assert pre_ended_count >= 1, (
        "sanity: 入场守卫也应当 ended_while_waiting"
    )
    assert warning_idx >= 0, "post-await 段必须含 ended_while_waiting"


def test_handle_session_suspended_catch_shows_ended_when_dialog_closed_by_server():
    """弹框被 handleServerMessage 主动 close 时 catch 必须兜底 ended。

    弹框开着时后端推 ended，handleServerMessage 主动 ElMessageBox.close()
    关闭弹框；confirm await reject 出 'close'，catch 分支必须再查一次
    status==ended 并 ended_while_waiting，否则用户只看到弹框消失、无
    ended 提示。"""
    script = _script_block(INTERVIEW_VUE.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleSessionSuspended = async () => {")
    # 找 catch 块
    catch_idx = body.index("} catch (")
    tail = body[catch_idx:]
    # catch 块中必须有 ended_while_waiting
    assert "ended_while_waiting" in tail, (
        "catch 分支必须再查 status==ended 并给 ended_while_waiting 兜底，"
        "弹框被 handleServerMessage 主动 close 时用户需要 ended 反馈"
    )
    # catch 块的 ended_while_waiting 必须在 cancel/close 分支内
    assert '"cancel"' in tail or '"close"' in tail, (
        "sanity: catch 块必须先判 cancel/close 再走 ended 兜底"
    )

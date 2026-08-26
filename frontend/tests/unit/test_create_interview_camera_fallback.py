"""PR #69 评审：拍照识别模块 4 处失败/空值路径兜底。

`CreateInterviewDialog.vue` 的相机流程在异常/空文本/重入路径下会留下卡死
状态（按钮永远 loading+disabled / 摄像头打不开但 panel 不退出）。本测试
守住 4 处兜底契约：
1. submitRecognition 走 try/finally 重置 cameraRecognizing
2. retakePhoto 接 openCamera 返回值，失败时关闭面板
3. recognizePhoto 给 snap 套 try/catch（readyState 覆盖不到 getContext/toBlob null）
4. handleFileChange 空文本与异常分支关闭面板
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIALOG = ROOT / "src" / "components" / "interview" / "CreateInterviewDialog.vue"


def _script_block(text: str) -> str:
    start = text.index("<script")
    end = text.index("</script>", start)
    return text[start:end]


def _function_body(script: str, signature: str) -> str:
    """截取从签名开始到下一个顶层 const/function/exports 之间的源码。"""
    start = script.index(signature)
    # 找下一个顶层声明
    tail = script[start + len(signature):]
    end_candidates = []
    for marker in ("\nconst ", "\nfunction ", "\nwatch(", "\nonMounted(", "\nexport "):
        idx = tail.find(marker)
        if idx >= 0:
            end_candidates.append(idx)
    end = min(end_candidates) if end_candidates else len(tail)
    return script[start:start + len(signature) + end]


def test_submit_recognition_resets_via_finally():
    """成功 closeActivePanel / 空文本 early return / catch 三支都进 finally 重置 cameraRecognizing。"""
    script = _script_block(DIALOG.read_text(encoding="utf-8"))
    body = _function_body(script, "const submitRecognition = async () => {")
    assert "finally" in body, "submitRecognition 必须有 finally 块"
    # finally 里至少出现一次 cameraRecognizing.value = false
    finally_idx = body.rindex("finally")
    after_finally = body[finally_idx:]
    assert "cameraRecognizing.value = false" in after_finally, (
        "finally 块必须重置 cameraRecognizing，否则重入拍照面板按钮永远 loading"
    )


def test_retake_photo_checks_open_camera_return():
    """retakePhoto 必须接 openCamera 返回值；失败时 message + closeActivePanel。"""
    script = _script_block(DIALOG.read_text(encoding="utf-8"))
    body = _function_body(script, "const retakePhoto =")
    assert "await openCamera()" in body, "retakePhoto 必须 await openCamera() 而不是 void 丢弃"
    assert "!opened" in body or "if (!opened)" in body, (
        "retakePhoto 必须判 openCamera 返回值，失败分支要给恢复路径"
    )
    # 失败分支里至少出现 message 和 closeActivePanel
    opened_idx = body.index("await openCamera()")
    fail_branch = body[opened_idx:]
    assert "message(" in fail_branch, "失败分支必须有 toast 提示"
    assert "closeActivePanel()" in fail_branch, "失败分支必须 closeActivePanel 让用户退出"


def test_recognize_photo_wraps_snap_in_try_catch():
    """recognizePhoto 的 snap 可能 throw（getContext null / toBlob null），必须 try/catch。"""
    script = _script_block(DIALOG.read_text(encoding="utf-8"))
    body = _function_body(script, "const recognizePhoto = async () => {")
    # 必须用 try 包裹 snapCamera
    assert "try {" in body, "recognizePhoto 必须用 try 包 snap"
    snap_idx = body.index("snapCamera(video)")
    assert "try" in body[:snap_idx], "try 块必须在 snapCamera 之前开始"


def test_handle_file_change_closes_panel_on_empty_and_error():
    """handleFileChange 的空文本与异常分支必须 closeActivePanel，否则用户卡死。"""
    script = _script_block(DIALOG.read_text(encoding="utf-8"))
    body = _function_body(script, "const handleFileChange = async (event: Event) => {")
    # 空文本分支必须在 message 后调 closeActivePanel
    empty_branch_start = body.index('if (!text)')
    # 找空文本分支的结束位置（下一个 return 或下个 } 配对起点），简化用下一个
    # return 或 closeActivePanel 关键字之一即可。
    tail_after_empty = body[empty_branch_start:]
    next_return = tail_after_empty.find("return")
    assert next_return > 0
    empty_branch = tail_after_empty[:next_return + len("return")]
    assert "closeActivePanel()" in empty_branch, (
        "空文本分支必须 closeActivePanel 让用户回到方式选择重试"
    )
    # catch 分支同样必须有 closeActivePanel
    catch_idx = body.index("} catch (error)")
    catch_branch = body[catch_idx:]
    assert "closeActivePanel()" in catch_branch, (
        "catch 分支也必须 closeActivePanel，让用户决定重试或换路径"
    )
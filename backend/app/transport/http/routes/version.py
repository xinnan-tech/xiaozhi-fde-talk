"""GET /api/v1/version —— about 页用的后端版本号。

放在这里而不是 diagnostics.py 的理由：
- diagnostics.py 里所有端点都 require_admin（POST 触发真实 ASR/LLM/OCR 调用，
  烧额度 + 占 ASR 并发），版本号只是元数据读，不属于"诊断"语义
- /health 与 /ready 主动剥掉 __version__（health.py 注释：版本号是侦察信号，
  外网探到 X.Y 直接拿到 CVE 靶标）—— 那些端点给公网探测器和编排器轮询
- 本端点挂 get_current_user：任何登录用户可见，但匿名访客 401 → 前端 about 页
  （about 在路由白名单里）降级显示 "—"，不会向公网泄漏版本号
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user

router = APIRouter()


@router.get("/version")
async def get_version(_: CurrentUser = Depends(get_current_user)):
    """返回 app.__version__。

    仅暴露一个字段：app 版本号。不返回 protocol_version / template_version /
    python 版本 / 依赖版本——这些是侦察信号叠加，按需再加。
    """
    return {"version": __version__}
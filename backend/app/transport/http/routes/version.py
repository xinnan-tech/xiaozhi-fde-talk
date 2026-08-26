"""GET /api/v1/version —— about 页用的后端版本号。

鉴权策略：
- 用 get_current_user_optional 而非 get_current_user：未登录不返 401，
  而是 200 + {"version": ""}。这是 about 页所在的"白名单"语义 —— about
  本来就不要求登录，匿名访问不该触发"登录状态已过期"toast（issue #77）
- 真实版本号仅登录用户可见：匿名访客拿到空字符串，向公网探测者不暴露
  app 版本号（保留原设计的反侦察意图）

放在这里而不是 diagnostics.py 的理由：
- diagnostics.py 里所有端点都 require_admin（POST 触发真实 ASR/LLM/OCR 调用，
  烧额度 + 占 ASR 并发），版本号只是元数据读，不属于"诊断"语义
- /health 与 /ready 主动剥掉 __version__（health.py 注释：版本号是侦察信号，
  外网探到 X.Y 直接拿到 CVE 靶标）—— 那些端点给公网探测器和编排器轮询
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from app import __version__
from app.domain.auth import CurrentUser
from app.transport.http.dependencies import get_current_user_optional

router = APIRouter()


@router.get("/version")
async def get_version(
    user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """返回 app.__version__。

    已登录用户 → 真实版本号；匿名 → 空字符串（前端 about 页把空值当
    "未拉到"处理，降级为只显示前端版本）。不返回 protocol_version /
    template_version / python 版本 / 依赖版本——这些是侦察信号叠加，
    按需再加。
    """
    return {"version": __version__ if user is not None else ""}
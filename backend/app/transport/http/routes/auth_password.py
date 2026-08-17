"""admin REST：POST /admin/auth/password 修改指定用户密码。

P2-7: 独立端点，不再走 ConfigStore.demo_password（M9：旧 admin UI 改密无效）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.auth import CurrentUser
from app.persistence.repositories.user import user_repo
from app.transport.http.dependencies import require_admin
from app.transport.http.schemas import AdminPasswordChangeRequest

router = APIRouter(prefix="/admin/auth", tags=["admin"])


@router.post("/password")
async def change_password(
    body: AdminPasswordChangeRequest,
    _admin: CurrentUser = Depends(require_admin),
) -> dict[str, bool]:
    """修改指定用户密码（按 username）。"""
    ok = await user_repo.update_password_auto(body.username, body.new_password)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user not found: {body.username}")
    return {"ok": True}
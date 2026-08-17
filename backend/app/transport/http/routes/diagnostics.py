"""/api/v1/diagnostics — 部署后连通性自检。

- POST /diagnostics          并发跑 ASR + LLM
- POST /diagnostics/asr      单跑 ASR
- POST /diagnostics/llm      单跑 LLM

结果结构统一为 {ok, code, message, latency_ms, detail?}（详见 services/diagnostics.py）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.domain.auth import CurrentUser
from app.services.diagnostics import diagnose_all, diagnose_asr, diagnose_llm
from app.transport.http.dependencies import require_admin

router = APIRouter(prefix="/diagnostics")


@router.post("")
async def run_all(user: CurrentUser = Depends(require_admin)):
    return await diagnose_all()


@router.post("/asr")
async def run_asr(user: CurrentUser = Depends(require_admin)):
    return await diagnose_asr()


@router.post("/llm")
async def run_llm(user: CurrentUser = Depends(require_admin)):
    return await diagnose_llm()
"""skill 执行器。

MVP 直接调用内置异步函数，并提供统一超时与失败降级。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from app.services.skill.registry import SkillArtifact, get_skill

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 5.0


@dataclass
class SkillResult:
    ok: bool
    artifact: Optional[SkillArtifact] = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "error": self.error,
        }


async def invoke_skill(skill_id: str, inputs: dict | None = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> SkillResult:
    definition = get_skill(skill_id)
    if definition is None:
        return SkillResult(ok=False, error=f"unknown skill: {skill_id}")
    try:
        artifact = await asyncio.wait_for(definition.handler(inputs or {}), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("技能执行超时：%s", skill_id)
        return SkillResult(ok=False, error=f"skill timeout: {skill_id}")
    except Exception as e:  # noqa: BLE001
        logger.exception("技能执行失败：%s", skill_id)
        return SkillResult(ok=False, error=f"{type(e).__name__}: {e}")
    return SkillResult(ok=True, artifact=artifact)

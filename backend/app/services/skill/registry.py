"""内置 skill 注册表。

MVP 只允许后端内置 skill，不加载用户代码。生产级 sandbox / 进程隔离后加。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional


SkillHandler = Callable[[dict], Awaitable["SkillArtifact"]]


@dataclass
class SkillArtifact:
    """skill 执行产物。MVP 主要返回可直接嵌入报告的 Markdown 文本。"""

    mime: str
    content: str = ""
    url: str = ""
    ttl: int = 0
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "mime": self.mime,
            "content": self.content,
            "url": self.url,
            "ttl": self.ttl,
            "meta": self.meta,
        }


@dataclass
class SkillDefinition:
    id: str
    name: str
    description: str
    handler: SkillHandler
    use_in: dict[str, bool] = field(default_factory=lambda: {"report": True, "coaching": False})
    input_schema: dict = field(default_factory=dict)

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "use_in": self.use_in,
            "input_schema": self.input_schema,
        }


_REGISTRY: dict[str, SkillDefinition] = {}


def register_skill(definition: SkillDefinition) -> None:
    _REGISTRY[definition.id] = definition


def get_skill(skill_id: str) -> Optional[SkillDefinition]:
    return _REGISTRY.get(skill_id)


def list_skills() -> list[SkillDefinition]:
    return sorted(_REGISTRY.values(), key=lambda s: s.id)


def list_public_skills() -> list[dict]:
    return [s.public_dict() for s in list_skills()]


def _load_builtins() -> None:
    from app.services.skill import builtins  # noqa: F401 触发注册


_load_builtins()

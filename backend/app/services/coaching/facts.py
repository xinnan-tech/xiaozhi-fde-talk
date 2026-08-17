"""事实卡管理（三层记忆第二层）。

FactDatabase 在 transcript 段追加时自动维护 fact 索引（key → seg_id[]）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

from app.domain.coaching import FactItem

logger = logging.getLogger(__name__)


@dataclass
class FactDatabase:
    """事实卡集合，按 key 索引。"""
    _by_key: dict[str, FactItem] = field(default_factory=dict)

    def add(self, key: str, value: str, seg_id: str) -> None:
        if key in self._by_key:
            sources = self._by_key[key].source
            if seg_id not in sources:
                sources.append(seg_id)
        else:
            self._by_key[key] = FactItem(key=key, value=value, source=[seg_id])

    def remove(self, key: str) -> None:
        self._by_key.pop(key, None)

    def extend(self, facts: Iterable[FactItem]) -> None:
        for f in facts:
            self.add(f.key, f.value, f.source[0] if f.source else "")

    def get(self, key: str) -> FactItem | None:
        return self._by_key.get(key)

    def all(self) -> list[FactItem]:
        return list(self._by_key.values())

    def by_seg_id(self, seg_id: str) -> list[FactItem]:
        return [f for f in self._by_key.values() if seg_id in f.source]

    def as_text(self) -> str:
        if not self._by_key:
            return "（无事实卡）"
        return "\n".join(
            f"- {f.key}：{f.value}（来源：{', '.join(f.source)}）"
            for f in sorted(self._by_key.values(), key=lambda x: x.key)
        )

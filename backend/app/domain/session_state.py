"""会话运行时状态（纯领域对象）。

后端持有 + 持久化（经 Repository）。含元信息（Session）+ 辅导清单 + skipped/ignored +
覆盖索引 + transcript。coaching 引擎读写 items/coverage；这里只定义容器
+ 从模板种出初始 todo 清单。

【分层】原位于 services/sessions/state.py，因 persistence.repositories 需要它做
ORM↔状态映射，迁到 domain/ 避免 persistence → services 的反向依赖（import-linter 契约）。
services/sessions/state.py 保留 re-export 兼容旧导入路径。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.coaching import CoachingItem, ItemStatus
from app.domain.session import Session, SessionStatus, TranscriptSegment

_SEG_ID_RE = re.compile(r"s(\d+)$")


@dataclass
class SessionState:
    session: Session
    items: list[CoachingItem] = field(default_factory=list)
    skipped_ids: set[str] = field(default_factory=set)
    ignored_ids: set[str] = field(default_factory=set)
    coverage: dict[str, list[str]] = field(default_factory=dict)  # item_id -> [seg_id]
    transcript: list[TranscriptSegment] = field(default_factory=list)
    _next_seg_id: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        # 计数器对齐已有 transcript 中的最大 seg 号：重载（DB→state）后 transcript
        # 可能已被软上限截断，直接从 0 起会回退、与仍存的旧 id 冲突。
        peak = 0
        for seg in self.transcript:
            m = _SEG_ID_RE.match(seg.seg_id)
            if m:
                peak = max(peak, int(m.group(1)))
        self._next_seg_id = peak

    @classmethod
    def initial(cls, session: Session, template) -> "SessionState":
        """从模板 must_ask 种初始 todo 清单（首算前占位；首算会重填）。"""
        items = [
            CoachingItem(
                id=m.id,
                text=m.text,
                status=ItemStatus.TODO,
                priority=m.priority if m.priority is not None else 99,
                desc=m.desc,
            )
            for m in template.coaching.must_ask
        ]
        return cls(session=session, items=items)

    @property
    def status(self) -> SessionStatus:
        return self.session.status

    @property
    def user_id(self) -> str | None:
        return self.session.user_id

    def next_seg_id(self) -> str:
        """分配下一个 seg_id（s1, s2, ...）。独立自增计数器，transcript 增减不影响。"""
        self._next_seg_id += 1
        return f"s{self._next_seg_id}"

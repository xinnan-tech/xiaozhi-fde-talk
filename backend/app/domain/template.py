"""模板结构（pydantic）。

模板是纯数据，是辅导 / 报告 / 安全的唯一真相源。
列宽约束对齐 TemplateRecord 的 DB 列宽：admin 经 JSON / AI 生成超长字段
会在 pydantic 层就拒，避免走到 SQLAlchemy 抛 DataError 500。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# 列宽对齐 TemplateRecord（迁移 0002_templates_to_db）：name=128 / icon_url=512 /
# icon_alt=32 / id=64 / version=16
_ID_MAX = 64
_NAME_MAX = 128
_ICON_URL_MAX = 512
_ICON_ALT_MAX = 32
_VERSION_MAX = 16


class BaseField(BaseModel):
    """会话基础信息字段定义。"""
    key: str = Field(max_length=64)
    label: str = Field(default="", max_length=128)
    type: str = "text"            # text / datetime / ...
    required: bool = False
    # default：建访谈时预填的值（空串=无；只填空字段，不覆盖用户输入）
    # placeholder：输入框灰字示例提示（空串=无；不参与提交）
    default: str = Field(default="", max_length=128)
    placeholder: str = Field(default="", max_length=128)


class SetupBlock(BaseModel):
    """创建访谈入口：语音优先设置。"""
    intro: str = ""                                       # 一句话口述提示
    extract_to: list[str] = Field(default_factory=list)   # 抽取映射到的字段 key
    required: list[str] = Field(default_factory=list)     # 必填字段 key


class SessionBlock(BaseModel):
    name: str = ""
    goal: str = ""
    base_fields: list[BaseField] = Field(default_factory=list)
    setup: SetupBlock = Field(default_factory=SetupBlock)
    # 访谈名称/访谈目标是建访谈表单的固定伪字段，不进 base_fields
    # （base_fields 只描述 base_info 的业务字段，goal 甚至不在 base_info），
    # 默认值单独放这：空串=无，建访谈时只填空字段，不覆盖用户输入
    title_default: str = Field(default="", max_length=128)
    goal_default: str = Field(default="", max_length=128)


class MustAskItem(BaseModel):
    """必问底座条目。固定 id（永不变）；可声明 priority / desc。"""
    id: str = Field(max_length=64)
    text: str
    priority: Optional[int] = None
    desc: str = ""


class CoachingBlock(BaseModel):
    playbook: str = ""
    must_ask: list[MustAskItem] = Field(default_factory=list)


class ReportBlock(BaseModel):
    """报告 = Markdown 骨架。"""
    doc: str = ""


class Template(BaseModel):
    # id 允许空串：AI 生成时若 LLM 给非法 id 会置空，交给编辑器让用户定；
    # loader._validate 在落库路径上再校验 id 格式（非空 + 正则）
    id: str = Field(default="", max_length=_ID_MAX)
    version: str = Field(default="1", max_length=_VERSION_MAX)
    icon_url: str = Field(default="", max_length=_ICON_URL_MAX)
    icon_alt: str = Field(default="", max_length=_ICON_ALT_MAX)
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    session: SessionBlock = Field(default_factory=SessionBlock)
    coaching: CoachingBlock = Field(default_factory=CoachingBlock)
    report: ReportBlock = Field(default_factory=ReportBlock)
    safety: list[dict[str, Any]] = Field(default_factory=list)

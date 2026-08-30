"""模板结构（pydantic）。

模板是纯数据，是辅导 / 报告 / 安全的唯一真相源。
列宽约束对齐 TemplateRecord 的 DB 列宽：admin 经 JSON / AI 生成超长字段
会在 pydantic 层就拒，避免走到 SQLAlchemy 抛 DataError 500。
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# 列宽对齐 TemplateRecord（迁移 0002_templates_to_db）：name=128 / icon_url=512 /
# icon_alt=32 / id=64 / version=16
_ID_MAX = 64
_NAME_MAX = 128
_ICON_URL_MAX = 512
_ICON_ALT_MAX = 32
_VERSION_MAX = 16

# base_fields.key 正则：英文小写开头，后跟字母/数字/下划线（#6）
# 与 Python 变量名习惯一致；空串 / 中文 / 连字符 / 大写 自动 422
_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"

# name 字符串约束：strip_whitespace + min/max 长度（#7）。
# 用 Annotated + StringConstraints 而不是 Field(strip_whitespace=True)：
# 后者已在 Pydantic 2.10 标记为 deprecation，并被识别为「extra」忽略掉，
# 实际不生效；StringConstraints 是 v2 推荐的字段约束写法。
# 模块级定义让 pydantic 在解析 Template 时能解析到 _NameStr 前向引用
_NameStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=_NAME_MAX),
]


class BaseField(BaseModel):
    """会话基础信息字段定义。"""
    # key 空串 / 中文会破坏 base_info 字典键与报告 {{session.<key>}} 占位符；
    # 这里用 pattern 兜底（#6）
    key: str = Field(pattern=_KEY_PATTERN, max_length=64)
    label: str = Field(default="", max_length=128)
    # type 仅允许三类，非法值 422（#5）——前端按 type 分支渲染控件，
    # 未知值会落到 <el-input> 文本框分支，UI 与行为不一致
    type: Literal["text", "datetime", "duration"] = "text"
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
    # 历史上有「会话名称」字段（`session.name`），全代码搜了一遍没有任何读路径
    # （生成器种子还填了示例值如 "用户/需求访谈" / "客户满意度回访"）——纯死字段，
    # 却和「访谈名称默认值 / 访谈名称」形成三胞胎同义混淆。#16 同名清理时一并删
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
    # extra="forbid" 防多写字段被静默吞（如 mustAsk 错写为 must_ask）（#9）；
    # 与 CreateInterviewRequest / LoginRequest 等惯例对齐
    model_config = ConfigDict(extra="forbid")

    # id 允许空串：AI 生成时若 LLM 给非法 id 会置空，交给编辑器让用户定；
    # loader._validate 在落库路径上再校验 id 格式（非空 + 正则）
    id: str = Field(default="", max_length=_ID_MAX)
    version: str = Field(default="1", max_length=_VERSION_MAX)
    icon_url: str = Field(default="", max_length=_ICON_URL_MAX)
    icon_alt: str = Field(default="", max_length=_ICON_ALT_MAX)
    # strip_whitespace 让 "   " 这种纯空格 trim 后判空（#7）——
    # 仅靠 min_length=1 会让三个空格蒙混过关，列表里显示为空白行
    name: _NameStr
    # session / coaching / report 不给默认值（#3）：原来用 default_factory
    # 会让「POST body 完全不传 session」返回 200 + 空壳 session，悄无声息
    # 把好模板改成空壳；现在缺则 422 把问题暴露在前端
    session: SessionBlock
    coaching: CoachingBlock
    report: ReportBlock
    safety: list[dict[str, Any]] = Field(default_factory=list)

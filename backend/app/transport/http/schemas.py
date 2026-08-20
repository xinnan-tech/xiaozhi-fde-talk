"""HTTP 请求/响应 DTO。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: str
    username: str
    role: str = "user"


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo


class AdminPasswordChangeRequest(BaseModel):
    """P2-7: admin 改指定用户密码（独立于 ConfigStore.demo_password）。"""
    username: str
    # ≥8 位最低强度；72 是 bcrypt 输入上限，超长直接拒绝而不是静默截断
    new_password: str = Field(min_length=8, max_length=72)


class TemplateSummary(BaseModel):
    id: str
    name: str
    icon_url: str
    icon_alt: str
    version: str


class TemplateListResponse(BaseModel):
    items: list[TemplateSummary]


class InvokeSkillRequest(BaseModel):
    inputs: dict = {}


class CreateInterviewRequest(BaseModel):
    template_id: str
    base_info: dict = {}
    goal: Optional[str] = None


class UpdateInterviewRequest(BaseModel):
    base_info: Optional[dict] = None
    goal: Optional[str] = None


class InterviewStatisticsResponse(BaseModel):
    in_progress: int
    week_finish: int
    assist_discovery: int
    interview_coverage: int


class ExtractRequest(BaseModel):
    transcript: str
    template_id: str
    fields: list[str]
    field_labels: dict[str, str] = {}  # key -> label
    field_types: dict[str, str] = {}   # key -> type: text / datetime / duration
    current_values: dict[str, str] = {}  # key -> 当前已填的值（不覆盖）


class ExtractResponse(BaseModel):
    values: dict[str, str]


class OCRRequest(BaseModel):
    image_base64: str  # base64 编码的图片数据（不含 data URL 前缀）


class OCRResponse(BaseModel):
    text: str

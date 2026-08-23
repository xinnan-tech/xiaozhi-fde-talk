"""HTTP 请求/响应 DTO。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    # extra="forbid" 防止请求体注入多余字段被静默丢弃、未来 schema 字段扩张时
    # 形成静默越权路径。当前仅 username / password，其余一律 422。
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


class UserInfo(BaseModel):
    id: str
    username: str
    role: str = "user"


class LoginResponse(BaseModel):
    # 双 token 模型：access 短 TTL 用于业务鉴权，refresh 长 TTL 用于换 access。
    # 前端当前只解 access；refresh 等前端迁移到 httpOnly cookie 时再上。
    access_token: str
    refresh_token: str = ""
    token_type: str = "bearer"
    user: UserInfo


class RefreshRequest(BaseModel):
    # extra="forbid" 防 access token 被误投到 refresh 字段、其它字段被注入形成静默越权路径
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=1)


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=1)


class RegistrationStatusResponse(BaseModel):
    """注册开关状态。响应体仅暴露 allow_registration，不返 user_count / has_admin（防侦察）。"""
    allow_registration: bool


# 4-32 位字母/数字/下划线/连字符；与 User.username 列对齐。
# 注意：service.register_user 内部还会 .lower() 归一，pydantic 这层只管形态校验。
_USERNAME_RE = r"^[A-Za-z0-9_-]{4,32}$"


class RegisterRequest(BaseModel):
    """POST /auth/register 请求体。"""
    # extra="forbid" 防止 role / is_admin 等字段被静默注入后忽略。
    model_config = ConfigDict(extra="forbid")

    username: str = Field(pattern=_USERNAME_RE)
    # 8 是 password_policy.MIN_LENGTH，72 是 bcrypt 字节上限——超长静默截断或抛裸
    # ValueError 都不友好，前置拒绝。
    password: str = Field(min_length=8, max_length=72)
    confirm_password: str = Field(min_length=8, max_length=72)


class AdminResetPasswordRequest(BaseModel):
    """admin 重置指定用户的密码。

    仅持 admin token 才能调用，弱密码在路由层被 validate_password_strength
    二次兜底（pydantic min/max 只管形态，长度合规的弱密码仍需黑名单拒）。
    """
    # extra="forbid" 防止注入 user_id / target_user_id 等改指定对象字段。
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=8, max_length=72)


class ChangePasswordRequest(BaseModel):
    """普通用户自助改密：必须先验证旧密码。

    不限 admin role——任何持有效 token 的登录用户都能改自己密码。
    旧密码错误 → 401；新密码强度不通过 → 400（路由层 validate_password_strength）。
    """
    # extra="forbid" 防止注入 user_id / username 试图指定他人目标（cf70cee 提交加的
    # schema 当时未 forbid，4f2eb2e 用 query / body 注入测试兜底；此处硬化前瞻）。
    model_config = ConfigDict(extra="forbid")

    old_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)


class AdminUserInfo(BaseModel):
    """admin 列用户端点的响应项。显式不含 password_hash（防泄漏）。"""
    id: str
    username: str
    role: str
    # ISO 8601 字符串（DB 存带时区的 datetime，序列化前 .isoformat()）
    created_at: str
    # 可空：新老用户混跑期间旧行此列为 NULL
    password_changed_at: str | None = None


class TemplateSummary(BaseModel):
    id: str
    name: str
    icon_url: str
    icon_alt: str
    version: str


class TemplateListResponse(BaseModel):
    items: list[TemplateSummary]


class InvokeSkillRequest(BaseModel):
    # extra="forbid" 防止 inputs 里塞任意 key 被静默忽略——skill 执行器读 inputs
    # 字段做 LLM 提示，恶意 key 可能引诱 LLM 偏离原提示词意图。
    model_config = ConfigDict(extra="forbid")

    inputs: dict = {}


class CreateInterviewRequest(BaseModel):
    # extra="forbid" 防止 user_id / template_version 等隐字段被注入形成静默越权
    # （路径已由 get_current_user 提供 user.user_id，body 重复 user_id 必拒）。
    model_config = ConfigDict(extra="forbid")

    template_id: str
    base_info: dict = {}
    goal: Optional[str] = None


class UpdateInterviewRequest(BaseModel):
    # extra="forbid" 防止 user_id / status 等被注入改他人访谈或跳状态机。
    model_config = ConfigDict(extra="forbid")

    base_info: Optional[dict] = None
    goal: Optional[str] = None


class InterviewStatisticsResponse(BaseModel):
    in_progress: int
    week_finish: int
    assist_discovery: int
    interview_coverage: int


class ExtractRequest(BaseModel):
    # extra="forbid" 防止 system_prompt / template_id 注入影响 LLM 行为
    # （template_id 已被字段声明；多余 system_prompt 等会被 Pydantic 拒收）。
    model_config = ConfigDict(extra="forbid")

    transcript: str
    template_id: str
    fields: list[str]
    field_labels: dict[str, str] = {}  # key -> label
    field_types: dict[str, str] = {}   # key -> type: text / datetime / duration
    current_values: dict[str, str] = {}  # key -> 当前已填的值（不覆盖）


class ExtractResponse(BaseModel):
    values: dict[str, str]


class OCRRequest(BaseModel):
    # extra="forbid" 防止 filename / user_id 等附加字段被注入（图片元数据污染）。
    model_config = ConfigDict(extra="forbid")

    image_base64: str  # base64 编码的图片数据（不含 data URL 前缀）


class OCRResponse(BaseModel):
    text: str

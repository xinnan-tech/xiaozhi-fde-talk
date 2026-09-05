"""HTTP 请求/响应 DTO。"""
from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# base_info 单字段 / 整体字节上限。base_info 是 JSON 列，没有 per-field 索引，
# 大字段会让 list / detail / export 全量查询被单条记录拖慢。值按 UTF-8 字节计，
# 不按字符——防有人故意用 4-byte emoji 把字段撑爆。
BASE_INFO_VALUE_MAX_BYTES = 4 * 1024  # 4 KB / 字段
BASE_INFO_TOTAL_MAX_BYTES = 64 * 1024  # 64 KB / base_info 整体


def _validate_base_info_size(base_info: dict) -> None:
    """base_info 整体 / 单字段字节上限校验。

    整体按 ``json.dumps(base_info, ensure_ascii=False, default=str)`` 后的 UTF-8
    字节数计——含 key、``{}`` / ``,`` / 引号等结构开销，与 DB 实际落库体积一致。
    单字段按 value 序列化字节 + 对应 key 字节合计判（key 字节不能漏算，否则
    可用长 key + 小 value 绕过单字段上限）。

    ``default=str`` 让 ``datetime`` / ``Decimal`` / ``set`` 等非 JSON 原生类型
    走字符串兜底，避免裸 ``TypeError`` 上抛为 500。
    """
    from app.core.i18n import Keys
    from app.core.i18n.errors import I18nError

    total_bytes = len(
        json.dumps(base_info, ensure_ascii=False, default=str).encode("utf-8")
    )
    if total_bytes > BASE_INFO_TOTAL_MAX_BYTES:
        raise I18nError(
            Keys.SESSION_BASE_INFO_TOTAL_TOO_LARGE,
            http_status=422,
            byte_len=total_bytes,
            max_bytes=BASE_INFO_TOTAL_MAX_BYTES,
        )

    for field_name, value in base_info.items():
        field_name_bytes = len(field_name.encode("utf-8"))
        value_bytes = len(
            json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        )
        field_bytes = field_name_bytes + value_bytes
        if field_bytes > BASE_INFO_VALUE_MAX_BYTES:
            raise I18nError(
                Keys.SESSION_BASE_INFO_VALUE_TOO_LONG,
                http_status=422,
                field=field_name,
                byte_len=field_bytes,
                max_bytes=BASE_INFO_VALUE_MAX_BYTES,
            )


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
    # 8 与 password_policy.MIN_LENGTH 对齐；72 是 bcrypt 字节上限——超长静默截断
    # 或抛裸 ValueError 都不友好，前置拒绝。
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
    # extra="forbid" 防止注入 user_id / username 试图指定他人目标。
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


class AdminTemplateSummary(BaseModel):
    """admin 模板列表项。referenced=被访谈引用（前端删除保护提示）。"""
    id: str
    name: str
    icon_url: str
    icon_alt: str
    version: str
    updated_at: str | None = None
    referenced: bool


class TemplateGenerateRequest(BaseModel):
    """POST /admin/templates/generate 请求体（AI 一句话生成模板）。

    只生成不落库：返回的 Template 直接进编辑器，落库仍走 POST /admin/templates。
    """
    # extra="forbid"：brief 之外的字段（如 id）一律 422，防止借生成端点注入
    model_config = ConfigDict(extra="forbid")

    # 2000 与 generator._BRIEF_MAX_CHARS 对齐（那里是服务层二次兜底）
    brief: str = Field(min_length=1, max_length=2000)


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

    @model_validator(mode="after")
    def _check_base_info_size(self) -> "CreateInterviewRequest":
        _validate_base_info_size(self.base_info)
        return self


class UpdateInterviewRequest(BaseModel):
    # extra="forbid" 防止 user_id / status 等被注入改他人访谈或跳状态机。
    model_config = ConfigDict(extra="forbid")

    base_info: Optional[dict] = None
    goal: Optional[str] = None

    @model_validator(mode="after")
    def _check_base_info_size(self) -> "UpdateInterviewRequest":
        if self.base_info is not None:
            _validate_base_info_size(self.base_info)
        return self


class InterviewStatisticsResponse(BaseModel):
    in_progress: int
    week_finish: int
    assist_discovery: int
    interview_coverage: int


class ExtractRequest(BaseModel):
    # extra="forbid" 防止 system_prompt / template_id 注入影响 LLM 行为
    # （template_id 已被字段声明；多余 system_prompt 等会被 Pydantic 拒收）。
    model_config = ConfigDict(extra="forbid")

    transcript: str = Field(max_length=200_000)
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

"""ORM 表模型（SQLAlchemy DeclarativeBase）。

pydantic 运行时模型在 domain/。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TemplateRecord(Base):
    """访谈模板（原 backend/templates/*.json 文件已废弃，DB 化）。

    content 是真相源（完整 domain.template.Template 结构的 JSON）；name/
    icon/version 冗余列仅供列表展示，写入时从同一份 pydantic 模型序列化——
    整存整取，不存在部分更新，冗余列不会漂移。
    """
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    icon_url: Mapped[str] = mapped_column(String(512), default="")
    icon_alt: Mapped[str] = mapped_column(String(32), default="")
    version: Mapped[str] = mapped_column(String(16), default="1")
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SystemConfig(Base):
    """系统级配置 KV 存储（JWT 密钥等敏感配置）。

    启动时通过 JWTSecretResolver 读取/写入。备份数据库即备份密钥。
    """

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")
    # 改密时间戳：JWT pwd_ver claim 比对此值实现即时吊销；可空，迁移回填后才有值
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class InterviewRecord(Base):
    __tablename__ = "interviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(64), index=True)
    template_version: Mapped[str] = mapped_column(String(16), default="1")
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    base_info: Mapped[dict] = mapped_column(JSON, default=dict)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_batch_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    # 运行时状态（冷启动恢复 / 无状态 server 依赖完整持久化）
    coaching_items: Mapped[list] = mapped_column(JSON, default=list)
    skipped_ids: Mapped[list] = mapped_column(JSON, default=list)
    ignored_ids: Mapped[list] = mapped_column(JSON, default=list)
    coverage_index: Mapped[dict] = mapped_column(JSON, default=dict)
    # 键盘笔记(覆盖式;与 session_keyboard_text 表互为镜像,JSON 列做冷启动镜像
    # 避免每次 restart 都重新查 DB 触发重建 state.keyboard_text)
    keyboard_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 手写笔记段(append;与 handwriting_images 表互为镜像,只存成功注入的段)
    handwriting_notes: Mapped[list] = mapped_column(JSON, default=list)
    # 创建访谈时的整份模板快照（编辑模板不影响已创建访谈）；旧行 NULL=回退实时读
    template_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    consumed_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReportRecord(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interview_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    content_md: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    skill_outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    # 生成时的 transcript 指纹（sha256[:16]）。transcript 变 → 缓存失效、重生。
    # 旧行此字段为空：视为无匹配 → 重生一次后填上。
    transcript_signature: Mapped[str] = mapped_column(String(64), default="")
    # 生成时的 llm.output_language（zh_cn/zh_tw/en）。语种变 → 缓存失效、重生。
    # 旧行此字段为空：视为未标，定失效 → 强制重生一次后填上当前语种。
    output_language: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionKeyboardText(Base):
    """键盘笔记（每 session+user 唯一 1 行，UPSERT 覆盖语义）。

    复合 PK 物理保证唯一性,POST handler 直接走 INSERT ... ON CONFLICT DO UPDATE
    无需应用层锁。`client_created_at` 保留用户「最初提交时刻」，`updated_at`
    表达「最后一次修改」。
    """
    __tablename__ = "session_keyboard_text"

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    text: Mapped[str] = mapped_column(Text, default="")
    client_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class HandwritingImage(Base):
    """手写笔记（每张图 1 行,append 语义）。

    `image_hash` 按 (user_id, image_hash) 联合唯一索引判重——同一用户
    连点提交/网络重试不会产生重复行,跨用户不去重防数据归属混乱。

    `ocr_status` 状态机:n/a（保留）/ pending / done / failed。
    `injected_at` 记录是否已注入 state.handwriting_notes,重启 session 后
    通过该字段判断是否需要重注入(本轮不实现,字段保留)。
    """
    __tablename__ = "handwriting_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    image_base64: Mapped[str] = mapped_column(Text)
    image_format: Mapped[str] = mapped_column(String(8))
    image_bytes_size: Mapped[int] = mapped_column(Integer)
    ocr_status: Mapped[str] = mapped_column(String(16), default="pending")
    text: Mapped[str] = mapped_column(Text, default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    image_hash: Mapped[str] = mapped_column(String(64))
    injected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # 画板 state(笔触 / 状态 JSON)——前端自增 canvas_index(1/2/3...)
    # 与同一行 image 共享生命周期:改画板 + 改图可一次 POST 完成,各自独立
    # UPSERT(各自按 hash 跳过)。payload 不进 LLM 上下文——LLM 只看 OCR 文本。
    canvas_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canvas_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    canvas_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("user_id", "image_hash", name="uq_handwriting_user_hash"),
        # 同一 session+user 下 canvas_index 唯一(可空 → 多行 NULL 允许)
        UniqueConstraint(
            "session_id", "user_id", "canvas_index",
            name="uq_handwriting_canvas_index",
        ),
        Index("ix_handwriting_session_created", "session_id", "created_at"),
    )

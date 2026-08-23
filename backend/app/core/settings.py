"""启动期配置（pydantic-settings）。

字段仅承载环境变量驱动的静态项（服务地址、数据库、JWT 算法、日志、部署模式）；
运行期可调的 LLM/ASR/辅导/会话/演示账号等 19 项见 app.core.config_store。

JWT 密钥说明：不在此处配置。运行时由 app.core.secret.JWTSecretResolver 从
system_config 表读取；缺失则自动生成并写回。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """启动期静态配置（环境变量驱动）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- 服务 ---
    env: Literal["dev", "test", "prod"] = "dev"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_file: str = ""  # 空=只控制台；设路径则额外写结构化 JSON 文件

    # --- 数据库（MVP 用 SQLite，prod 切 MySQL/PG）---
    db_url: str = "sqlite+aiosqlite:///./xiaozhi_fde_talk.db"
    db_echo: bool = False

    # --- 鉴权（JWT）---
    # jwt_secret 由 SecretResolver 在 lifespan 中从 DB 加载/生成后注入到 settings，
    # 此处不暴露给环境变量配置（避免懒人部署共享密钥风险）。
    jwt_secret: Optional[str] = None
    jwt_algorithm: str = "HS256"

    # --- 部署 ---
    # True: 后端托管前端 SPA（Docker 部署模式）；False: 仅纯 API（dev 模式）
    serve_frontend: bool = True

    # --- LLM（辅导重算 + 报告生成；可插拔）---
    llm_type: str = "openai"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "qwen-plus"

    # --- ASR（可插拔；adapters/asr/factory.py 按 asr_type 实例化）---
    asr_type: Literal["funasr_server"] = "funasr_server"
    asr_sample_rate: int = 16000
    # 默认空串：prod 由 _validate_prod 拒绝 localhost/127.0.0.1，dev/test 时
    # 由 adapters/asr/factory 给出 localhost fallback 或显式 env 注入。
    # 历史默认 wss://localhost:10096 在容器内 prod 部署被解析到容器自身，ASR 静默挂。
    asr_ws_url: str = ""

    # --- 会话运行时 ---
    session_grace_period_s: float = 60.0

    # --- CORS（上公网必填）---
    cors_origins: str = ""  # 逗号分隔，如 "https://app.example.com"

    @model_validator(mode="after")
    def _validate_prod(self) -> "Settings":
        """生产环境强校验（DB_URL 必须为 MySQL/PostgreSQL；ASR_WS_URL 不能指向 localhost/127.0.0.1）。"""
        # 延迟导入：避免 settings 导入期拉起 i18n 子包（settings 被广泛 import）
        from app.core.i18n.errors import I18nError
        from app.core.i18n.messages import Keys
        if self.env == "prod":
            if not self.db_url.startswith(("mysql+", "postgresql+")):
                raise I18nError(Keys.SETTINGS_PROD_NO_SQLITE, http_status=400)
            # prod 的 ASR 地址必须真实可达：localhost/127.0.0.1 在容器内永远指向容器自身。
            # ws/wss 协议宿主部分做字符串检查即可——不同地址前缀的端口/路径被忽略，
            # 只要主机标识命中 localhost / 127.0.0.1 / 0.0.0.0 就拒。
            url = self.asr_ws_url.lower()
            if url.startswith(("ws://localhost", "wss://localhost",
                               "ws://127.0.0.1", "wss://127.0.0.1",
                               "ws://0.0.0.0", "wss://0.0.0.0")):
                raise I18nError(Keys.SETTINGS_PROD_ASR_LOCALHOST, http_status=400)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例（pydantic-settings 实例化有 .env 解析开销，缓存之）。"""
    return Settings()

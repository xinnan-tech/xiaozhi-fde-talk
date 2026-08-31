"""启动期配置（pydantic-settings）。

字段仅承载环境变量驱动的静态项（服务地址、数据库、JWT 算法、日志、部署模式）；
运行期可调的 LLM/ASR/辅导/会话/演示账号等 19 项见 app.core.config_store。

JWT 密钥说明：不在此处配置。运行时由 app.core.secret.JWTSecretResolver 从
system_config 表读取；缺失则自动生成并写回。

运行时数据文件（.env、SQLite DB 等）落在 backend/data/ 下，路径相对本文件解析，
不依赖进程 CWD——便于 Docker 用宿主卷直接挂载该目录。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# backend/app/core/settings.py → backend/ 是 parents[2]
BACKEND_ROOT: Path = Path(__file__).resolve().parents[2]
# 守门：本模块假设布局 backend/{app,migrations,...}/，若被打包成 wheel 装进
# site-packages/，parents[2] 会落到 site-packages/，data/.env 与 SQLite 都会被
# 写到错误位置。fail-fast 报清楚，让排查不用翻 alembic / 启动 traceback。
if not (BACKEND_ROOT / "migrations").is_dir():
    raise RuntimeError(
        f"app.core.settings 解析 BACKEND_ROOT={BACKEND_ROOT}，但其中无 "
        f"migrations/ 目录——文件被错误安装到非项目根路径？"
    )
DATA_DIR: Path = BACKEND_ROOT / "data"
# SQLite 不会自动创建父目录；data/ 一旦被误删（git clean / rm -rf）首次 DB 连接
# 会抛 unable to open database file，错误出在 engine 层，排查困难。显式 mkdir 兜底。
DATA_DIR.mkdir(parents=True, exist_ok=True)
# SQLite 默认 DB 文件绝对路径。SQLite URL 用 4 个斜杠前缀表示绝对路径。
_DEFAULT_DB_PATH: Path = DATA_DIR / "xiaozhi_fde_talk.db"
_DEFAULT_DB_URL: str = f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH}"


class Settings(BaseSettings):
    """启动期静态配置（环境变量驱动）。"""

    model_config = SettingsConfigDict(
        # 路径相对 backend/ 解析，不依赖进程 CWD；docker 部署时挂 data/ 卷即可。
        env_file=str(DATA_DIR / ".env"),
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
    db_url: str = _DEFAULT_DB_URL
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
    asr_type: Literal["funasr_server", "funasr_mock", "doubao_stream"] = "funasr_server"
    asr_sample_rate: int = 16000
    # asr.ws_url 不再走 .env：运行时唯一来源是系统配置 store（admin 后台可改），
    # 由 adapters/asr/factory / funasr_server 直接读 DB，未配时首请求即抛
    # ASRProviderError(ASR_URL_NOT_CONFIGURED, 502)。

    # --- 会话运行时 ---
    session_grace_period_s: float = 60.0

    # --- CORS（上公网必填）---
    cors_origins: str = ""  # 逗号分隔，如 "https://app.example.com"

    @model_validator(mode="after")
    def _validate_prod(self) -> "Settings":
        """生产环境强校验（DB_URL 必须为 MySQL/PostgreSQL）。

        ASR 地址不在此处校验：asr.ws_url 由系统配置 store 承载，未配置时
        adapters/asr 在首次 ASR 请求抛 ASRProviderError(ASR_URL_NOT_CONFIGURED, 502)，
        fail-fast 留给业务路径而不是启动期——方便 dev/test 默认值兜底。
        """
        # 延迟导入：避免 settings 导入期拉起 i18n 子包（settings 被广泛 import）
        from app.core.i18n.errors import I18nError
        from app.core.i18n.messages import Keys
        if self.env == "prod":
            if not self.db_url.startswith(("mysql+", "postgresql+")):
                raise I18nError(Keys.SETTINGS_PROD_NO_SQLITE, http_status=400)
        return self


def _env_var_to_field_map() -> set[str]:
    """Settings 类声明字段的「大写环境变量名」集合。

    pydantic-settings 的字段名 + alias（如果有）都换成大写。prod 启动期检查
    当前进程 env 里所有形如 ``FOO_BAR`` 的、且非空的值，是否都被 Settings 接住——
    未接住（typo 如 ``DATABASE_URL`` 应是 ``DB_URL``）即拒启动。
    """
    out: set[str] = set()
    for name, field in Settings.model_fields.items():
        out.add(name.upper())
        if isinstance(field.alias, str):
            out.add(field.alias.upper())
        # 多 alias 的情况：pydantic v2 用 validation_alias
        va = getattr(field, "validation_alias", None)
        if isinstance(va, str):
            out.add(va.upper())
    # 非 Settings 字段但被代码直接读 os.environ 的「隐性配置」——这些不在
    # model_fields 里，但被 bootstrap / main.py / i18n 路径显式消费。
    # 不收纳会让 prod 启动误报它们是 typo。
    out.update({
        "APP_ENV",                  # bootstrap.init_db(env=...) 主开关
        "APP_DB_USE_ALEMBIC",       # bootstrap 兼容路径（prod 已强制）
        "WEB_CONCURRENCY",          # uvicorn workers
        "TESTING",                  # 未来 Pytest 全局钩子
        "PYTEST_CURRENT_TEST",      # pytest 自身
        "PYTEST_VERSION",
    })
    return out


# 进程内 env 中与我们 Settings 同名/同前缀的「无关但合法」白名单：
# 这些是被子进程 / shell / CI / docker compose 注入的全局变量，我们不强制接住
# ——若强接每次升级都得维护白名单，跟「拒 typo」的初衷相违。策略：在 Pydantic
# 走完 parse 后，比对 OS environ 里「大写」与已知字段名集合的差异——只取带下划线
# 且全大写的疑似应用配置量；典型误拼如 ``DATABASE_URL``（应是 DB_URL）会被识别。
_KNOWN_SYSTEM_ENV_PREFIXES = (
    "PATH", "HOME", "USER", "SHELL", "LANG", "LC_", "PWD", "OLDPWD",
    "TERM", "XDG_", "HOSTNAME", "LOGNAME", "MAIL", "EDITOR", "VISUAL",
    "DISPLAY", "TMPDIR", "SSH_", "GIT_", "NIX_", "CARGO_", "GO",
    "JAVA_", "NODE_", "PNPM_", "PIP_", "PYTHON", "VIRTUAL_ENV", "CONDA",
    "LS_", "PROMPT", "KUBERNETES", "AWS_", "AZURE_", "GCP_", "GITHUB_",
)


def _is_app_setting_name(name: str) -> bool:
    """粗筛：看起来像应用配置（带下划线 + 不在系统白名单）的 env 名。"""
    if "_" not in name:
        return False
    # pytest / Python 解释器 / Claude Code / shell 内部状态等已知系统 / 工具变量直接放行
    upper = name.upper()
    for prefix in _KNOWN_SYSTEM_ENV_PREFIXES:
        if upper.startswith(prefix):
            return False
    # Claude Code 与本机工具注入的大量 env（如 CLAUDE_CODE_SESSION_ID / ANTHROPIC_*）
    # 与本应用无关——前缀白名单拦截即可。
    if upper.startswith(("CLAUDE_", "ANTHROPIC_", "TAVILY_", "AI_", "AGENT_",
                          "NIX_", "NVM_", "_CE_", "TMUX_", "DBUS_")):
        return False
    return True


def check_prod_no_typo_env(strict: bool = False) -> list[str]:
    """prod 模式：扫 OS environ，把不在 Settings 字段白名单的疑似应用配置 env 名列出。

    返回值是「可能 typo 字段」清单。strict=True 时直接抛 I18nError 阻止启动；
    strict=False 时仅打印警告，保留 dev 临时覆盖灵活性。
    只在 settings.env == "prod" 时调用本函数。
    """
    from app.core.i18n.errors import I18nError
    from app.core.i18n.messages import Keys

    known = _env_var_to_field_map()
    suspects: list[str] = []
    for k in os.environ:
        if not _is_app_setting_name(k):
            continue
        if k.upper() in known:
            continue
        suspects.append(k)
    if not suspects:
        return []
    msg = f"未识别的 prod 环境变量（疑似拼写错）：{sorted(suspects)}"
    if strict:
        raise I18nError(Keys.SETTINGS_PROD_TYPO_ENV, http_status=400, names=msg)
    return suspects


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例（pydantic-settings 实例化有 .env 解析开销，缓存之）。"""
    return Settings()

"""uvicorn 启动逻辑。

被根目录 `main.py` 薄壳调用。
"""
from __future__ import annotations

import logging
import os
import sys

from app import __version__
from app.core.logging import configure_logging
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def _load_settings_or_exit():
    """加载配置；启动期配置错误（密码强度等）翻译成单行友好提示并立即退出。

    设计：与 lifespan 的 init_db 失败同款——stderr 单行 + os._exit，避开 uvicorn
    的 [error] Traceback 噪音，让 docker/systemd 用户一眼看到根因。

    注意：必须在 import `app.app` 之前调用——`app.app` 的 import 链会拉起
    `app.persistence.db`，而 db.py 模块级就会触发 Settings() 校验。若先 import
    `app.app` 再校验配置，password 错误会以不友好的 pydantic traceback 形式
    在 import 阶段抛出，绕过本函数的友好提示。
    """
    try:
        return get_settings()
    except Exception as e:  # noqa: BLE001
        # pydantic ValidationError 把 model_validator 抛的 ValueError 裹成
        # ValidationError(value_error=...)；按"取最短的原始错误信息"原则抽取。
        msg = _extract_user_message(e)
        print(f"\n[配置错误] {msg}\n", file=sys.stderr, flush=True)
        os._exit(2)


def _extract_user_message(e: BaseException) -> str:
    """从 pydantic ValidationError 里挖出业务错误原文（去掉字段路径/类型噪声）。"""
    # pydantic v2: ValidationError.errors() -> [{type, msg, loc, ...}]
    errors = getattr(e, "errors", None)
    if callable(errors):
        try:
            items = errors()
        except Exception:  # noqa: BLE001
            items = []
        for item in items:
            if item.get("type") == "value_error":
                ctx = item.get("ctx") or {}
                err = ctx.get("error") or item.get("msg") or ""
                # ValueError.__str__ 已经就是我们写在 password_policy 里的中文文案
                return str(err)
        # 兜底：取第一条 msg
        if items:
            return str(items[0].get("msg") or e)
    return str(e)


def main() -> None:
    # 1) 先校验配置（密码强度等）。必须在 import app.app 之前——见 _load_settings_or_exit。
    settings = _load_settings_or_exit()
    # 2) 配置 OK，再 import 装配层（其 import 链会拉起 db 连接池构建）
    from app.app import create_app

    # 在任何业务 import 之前配好结构化日志（统一 app + uvicorn 日志）
    log_config = configure_logging(settings.log_level, log_file=settings.log_file or None)

    import uvicorn

    logger.info("小智方糖 %s 启动中，监听 %s:%s", __version__, settings.host, settings.port)
    uvicorn.run(
        create_app(),
        host=settings.host,
        port=settings.port,
        log_config=log_config,
        log_level=settings.log_level.lower(),
        # WS keepalive：服务端每 20s 发 ping，pong 不回 20s 视为连接死。
        # 不开的话，TCP 静默掉（如 WiFi 抖动）要等内核默认 7200s 才能感知，
        # 期间所有 send 都会卡在 _send_lock 里直到 safe_send 2s 超时。
        ws_ping_interval=20.0,
        ws_ping_timeout=20.0,
    )


if __name__ == "__main__":
    main()

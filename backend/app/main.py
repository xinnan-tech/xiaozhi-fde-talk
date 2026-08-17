"""uvicorn 启动逻辑。

被根目录 `main.py` 薄壳调用。
"""
from __future__ import annotations

import logging

from app import __version__
from app.app import create_app
from app.core.logging import configure_logging
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
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

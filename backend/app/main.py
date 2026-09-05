"""uvicorn 启动逻辑。

被根目录 `main.py` 薄壳调用。
"""
from __future__ import annotations

import logging
import os
import sys

from app import __version__
from app.core.i18n import Keys, t
from app.core.i18n.locales import DEFAULT
from app.core.logging import configure_logging
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def _startup_msg(key: Keys, **params) -> str:
    """Resolve a startup message in the default locale.

    Startup runs before any HTTP request, so there is no negotiated locale
    to fall back on. Pin to ``DEFAULT`` for stable, deployment-locale-
    independent stderr output."""
    return t(key.value, locale=DEFAULT, **params)


def _exit_config_error(message: str) -> None:
    """打印一行配置错误到 stderr，然后用 SystemExit 退出。

    vs os._exit：SystemExit 是 BaseException 同族但走 Python 异常路径，
    uvicorn 之外的子进程 / 包装脚本能正常接住并清理现场；orchestrator 看
    到的是干净的退出码 2 而不是 abort 信号。但 uv_runner.run() 不会主动
    catch SystemExit——它在 uvicorn 启动前就已经 raise，过程根本还没跑起来。
    """
    print(f"\n[配置错误] {message}\n", file=sys.stderr, flush=True)
    raise SystemExit(2)


def _load_settings_or_exit():
    """加载配置；启动期配置错误（env 值非法等）翻译成单行友好提示并立即退出。

    设计：与 lifespan 的 init_db 失败同款——stderr 单行 + SystemExit(2)，
    避开 uvicorn 的 [error] Traceback 噪音，让 docker/systemd 用户一眼看到根因。
    SystemExit(2) 比 os._exit(2) 更友好：包装器 / 测试 / IDE debug 都能 catch，
    而退出码语义不变。

    注意：必须在 import `app.app` 之前调用——`app.app` 的 import 链会拉起
    `app.persistence.db`，而 db.py 模块级就会触发 Settings() 校验。若先 import
    `app.app` 再校验配置，错误会以不友好的 pydantic traceback 形式
    在 import 阶段抛出，绕过本函数的友好提示。
    """
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001
        _exit_config_error(_startup_msg(Keys.STARTUP_CONFIG_INVALID))
    # prod 模式额外扫一遍 env，拼错的 DATABSE_URL 等大写会被识别并拒启动。
    # dev/test 不强制，方便本地临时覆盖 / CI 注入怪变量。
    if settings.env == "prod":
        try:
            from app.core.settings import check_prod_no_typo_env
            check_prod_no_typo_env(strict=True)
        except Exception as e:  # noqa: BLE001
            from app.core.i18n.errors import I18nError
            if isinstance(e, I18nError):
                _exit_config_error(e.localized())
            _exit_config_error(str(e))
    return settings


def main() -> None:
    # 1) 先校验配置（密码强度等）。必须在 import app.app 之前——见 _load_settings_or_exit。
    settings = _load_settings_or_exit()
    # 2) 配置 OK，再 import 装配层（其 import 链会拉起 db 连接池构建）
    from app.app import create_app

    # 在任何业务 import 之前配好结构化日志（统一 app + uvicorn 日志）
    log_config = configure_logging(settings.log_level, log_file=settings.log_file or None)

    import uvicorn

    # WEB_CONCURRENCY: dev/single-worker 测试期保持 1；compose prod 设为 2~N 时
    # uvicorn 走多进程：每个 worker 独立进程模型，asyncio + 数据库池各自一份，
    # 因此 --workers > 1 必须配 DB 连接池上限（pool_size < 总连接数 / workers）。
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))
    logger.info("小智方糖 %s 启动中，监听 %s:%s（workers=%d）", __version__, settings.host, settings.port, workers)
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
        # WS 单帧字节上限：protocol 层提前拒绝超大帧，避免应用层 64 KB
        # 判断在整帧已缓冲进内存后才跑、拦不住瞬时内存吞噬。兜底逻辑在
        # handler._loop（按 UTF-8 字节 / bytes 长度判）。
        ws_max_size=64 * 1024,
        # 反向代理后的 X-Forwarded-For/Proto 让 request.client.host 拿到真实客户端 IP
        # ——request.client.host 是 proxy 时，所有用户共享一个桶，单点刷爆全员 429。
        # 默认信任 loopback / docker 网络：compose 默认网关 172.16.0.0/12、私网 10/8、
        # 本机 127.0.0.0/8；运维布在公网需在 .env 加 FORWARDED_ALLOW_IPS 覆盖
        # （与 .env.example 注释同步）。显式 "*" 不安全——攻击者可伪造 XFF 旁路
        # 限流桶与 /ws/v1/echo loopback 检查。
        proxy_headers=True,
        forwarded_allow_ips=os.getenv(
            "FORWARDED_ALLOW_IPS", "127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16",
        ),
        workers=workers if workers > 1 else None,
    )


if __name__ == "__main__":
    main()

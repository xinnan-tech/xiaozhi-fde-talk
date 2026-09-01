"""HTTPS 单进程启动器（Docker 容器专用入口）。

只跑一个 uvicorn + SSL，监听 HTTPS_PORT（默认 8848）；不再保留 HTTP 重定向
进程——客户端必须显式用 `https://host:8848/` 访问，浏览器手动信任自签名证书。

为什么单进程而不是 HTTP+HTTPS 双进程？
- 早期方案保留 HTTP 8000 + 自动 301 跳 HTTPS，便于局域网客户端用 IP 直接访问。
- 实测：浏览器必须 `https://...` 才能开麦克风，HTTP 重定向后客户端仍需走 HTTPS，
  多一跳意义不大，反而让容器多一个 uvicorn 进程 + 多 30MB 内存。
- 单 HTTPS 8848：与 dev Vite 端口一致，地址栏统一；内存省 ~30MB；启动逻辑
  从双 asyncio.gather + 双 signal handler 收敛到单 server。

工作进程数：
- WEB_CONCURRENCY=N：HTTPS 主进程开 N 个 worker（lifespan 在每个 worker 内
  跑一次——init_db、warm、idle watchdog、JWT secret）。
- proxy-headers + forwarded-allow-ips：取反代后的 X-Forwarded-For，让 request.client.host
  拿到真实客户端 IP；攻击者伪造 XFF 旁限流桶——必须收敛到 loopback / 私网段。
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys

import uvicorn


def _build_config(workers: int, https_port: int) -> uvicorn.Config:
    """构造 uvicorn.Config。

    forwarded_allow_ips 收敛到 loopback / RFC1918 私网段；公网部署由
    docker-compose 注入 FORWARDED_ALLOW_IPS 环境变量覆盖。显式 "*" 不可信——
    攻击者可伪造 XFF 旁路限流桶。
    """
    forwarded_allow_ips = os.getenv(
        "FORWARDED_ALLOW_IPS",
        "127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16",
    )
    return uvicorn.Config(
        "app.app:create_app",
        factory=True,
        host=os.getenv("HOST", "0.0.0.0"),
        port=https_port,
        ssl_keyfile=os.getenv("SSL_KEYFILE"),
        ssl_certfile=os.getenv("SSL_CERTFILE"),
        workers=workers,
        proxy_headers=True,
        forwarded_allow_ips=forwarded_allow_ips,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


async def _serve() -> None:
    https_port = int(os.getenv("HTTPS_PORT", "8848"))
    ssl_keyfile = os.getenv("SSL_KEYFILE")
    ssl_certfile = os.getenv("SSL_CERTFILE")
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))

    if not ssl_keyfile or not ssl_certfile:
        print(
            "[配置错误] SSL_KEYFILE / SSL_CERTFILE 必须设置",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(2)

    config = _build_config(workers, https_port)
    server = uvicorn.Server(config)

    # 信号处理：SIGINT / SIGTERM → 走 graceful shutdown。
    # tini 已经把 PID 1 信号转给我们，这里再注册到 loop 保证 asyncio task 取消。
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _trigger_stop() -> None:
        server.should_exit = True
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _trigger_stop)

    serve_task = asyncio.create_task(server.serve(), name="https")
    try:
        await asyncio.wait(
            [serve_task, asyncio.create_task(stop_event.wait(), name="stop")],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        _trigger_stop()
        await asyncio.gather(serve_task, return_exceptions=True)


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
# 子路径部署

生产环境默认部署在域名根路径 `/`。如果服务器根路径已经有其他项目，可以将本项目部署到子路径，例如 `/xiaozhi-fde-talk/`。

本项目支持两种部署形态，按需选用：

| 形态 | 是否需要反向代理 | 适用场景 |
|---|---|---|
| 单进程模式（默认推荐） | 否 | 单机部署、不想折腾 nginx、TLS 由上游网关终止 |
| 反向代理模式 | 是 | 多服务同域名分流、TLS 在本机终结、需要复杂路径路由 |

两种形态的前端 VITE_PUBLIC_PATH 配置相同；后端 SUBPATH 反代模式留空、单进程模式必须与前端一致。

## 1. 配置文件（前后端必须一致）

**前后端各有一个字段，值必须一字不差**（例如都写 `/xiaozhi-fde-talk`，结尾**不带**斜杠）。任一处不配 → 两边默认空 → 走根路径部署，前后端互通，不会有任何副作用。

### 前端：`frontend/.env.production`

构建前修改：

```env
VITE_PUBLIC_PATH = /xiaozhi-fde-talk/
```

值以**斜杠结尾**。恢复根路径部署时改回 `/`。

### 后端：`backend/.env` 或环境变量

后端用 pydantic-settings 读取 `SUBPATH` 环境变量，配置写在 `backend/.env` 里：

```env
SUBPATH=/xiaozhi-fde-talk
```

值以**斜杠结尾或不带**均可（启动时会归一化）。也可用环境变量直接覆盖：

```bash
SUBPATH=/xiaozhi-fde-talk python main.py
```

## 2. 重新构建

### Docker 部署

GHCR 预构建镜像不含本地 `VITE_PUBLIC_PATH` 改动，需本地重打：

```bash
docker compose build app --no-cache
docker compose up -d app
```

镜像编译细节参见 [本地编译 Docker 镜像](docker-build.md)。

### 源码部署

```bash
cd frontend && pnpm install --frozen-lockfile && pnpm build
cp -r dist/* ../backend/static/
```

后端 `python main.py` 启动时读 `SUBPATH` 自动带前缀，无需再编译。

## 3. 启动方式

任选一种。

### 3.1 单进程模式（无需反代）

最简单的方式。浏览器直接访问 `http://host:8000/xiaozhi-fde-talk/`，后端进程自己处理前缀剥离和静态托管。

```bash
SUBPATH=/xiaozhi-fde-talk python main.py
# 或 Docker：docker compose up -d app  （compose 里设置 environment.SUBPATH）
```

**原理**：后端内置 `_SubpathStripMiddleware` 拦截 `subpath/xxx`，剥前缀后区分处理——`/api/`、`/ws/` 透传给业务路由，其他走 StaticFiles。零反代、零配置、零额外进程。

> 注意：单进程模式下，后端 8000 端口的**根路径**（`http://host:8000/`）会返回 SPA 兜底 HTML，但里面的 `/api/...` 请求会 404。用户**必须访问子路径入口**（`/xiaozhi-fde-talk/`），不要访问根路径。

### 3.2 反向代理模式

服务器应将 `/xiaozhi-fde-talk/` 转发到本项目服务，并保留 WebSocket 转发能力。Nginx 示例：

```nginx
location = /xiaozhi-fde-talk {
    return 301 /xiaozhi-fde-talk/;
}

location /xiaozhi-fde-talk/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_http_version 1.1;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

`proxy_pass` 结尾的 `/` 会在转发时去掉 `/xiaozhi-fde-talk` 前缀，使后端继续接收 `/api/...` 和 `/ws/...` 路径。

**反代模式下后端不需要配置 `SUBPATH`**（前置反代已经把前缀剥掉）。但前端 `VITE_PUBLIC_PATH` 仍要配成 `/xiaozhi-fde-talk/`，否则浏览器不会带前缀打反代。

> Caddy / Traefik / 云负载均衡同理：把 `/xiaozhi-fde-talk/` 整段转发到后端，前缀在反代侧被剥离。

## 4. 验证

访问 `http://服务器地址/xiaozhi-fde-talk/`，确认页面资源、API 请求和语音 WebSocket 均正常。Hash 路由页面通常会显示为 `/xiaozhi-fde-talk/#/...`。

单进程模式下可直接查看后端日志确认前缀生效：

```
127.0.0.1:xxxxx - "GET /api/v1/auth/registration-status HTTP/1.1" 200       # 业务 API 已被 SUBPATH 剥离
127.0.0.1:xxxxx - "GET /static/js/index-xxxxx.js HTTP/1.1" 200              # 静态资源已被剥离
```

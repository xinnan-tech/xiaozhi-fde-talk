# 子路径部署

生产环境默认部署在域名根路径 `/`。如果服务器根路径已经有其他项目，可以将本项目部署到子路径，例如 `/xiaozhi-fde-talk/`。

本项目支持两种部署形态，按需选用：

| 形态 | 是否需要反向代理 | 适用场景 |
|---|---|---|
| 单进程模式（默认推荐） | 否 | 单机部署、不想折腾 nginx、TLS 由上游网关终止 |
| 反向代理模式 | 是 | 多服务同域名分流、TLS 在本机终结、需要复杂路径路由 |

两种形态的前端配置完全相同，区别只在第 3 步「启动方式」。

## 1. 配置文件（前后端必须一致）

子路径前后端各有一个字段：前端 `VITE_PUBLIC_PATH`、后端 `SUBPATH`。**单进程模式下两边要么都配且子路径一致，要么都不配**（默认空 → 根路径部署，前后端互通，无副作用）。只配一边、或值不一致 → 前端请求路径和后端路由对不上，404 / 白屏。反代模式是例外：前缀在反代侧剥离，后端不配 `SUBPATH`（见 3.2）。

书写格式略有差异，属正常现象：

- 前端 `VITE_PUBLIC_PATH` 以**斜杠结尾**：`/xiaozhi-fde-talk/`
- 后端 `SUBPATH` 结尾带不带斜杠均可：`/xiaozhi-fde-talk`（启动时归一化）

### 前端：`frontend/.env.production`

构建前修改：

```env
VITE_PUBLIC_PATH = /xiaozhi-fde-talk/
```

恢复根路径部署时改回 `/`。

### 后端：`backend/data/.env` 或环境变量

后端用 pydantic-settings 读取 `SUBPATH`，配置写在 `backend/data/.env`（首次部署先在 `backend/` 下执行 `cp .env.example data/.env`）：

```env
SUBPATH=/xiaozhi-fde-talk
```

也可用环境变量直接覆盖：

```bash
SUBPATH=/xiaozhi-fde-talk python main.py
```

### 本地开发（`pnpm dev`）也想走子路径时

`.env.development` 里把 `VITE_PUBLIC_PATH` 改成 `/xiaozhi-fde-talk/`，浏览器访问 `http://127.0.0.1:8848/xiaozhi-fde-talk/`。

**`VITE_API_URL` / `VITE_WS_BASE_URL` 是否要带子路径，取决于 dev 后端有没有配 `SUBPATH`，两边必须对齐，否则 API / WS 全部打不通：**

| dev 后端 `SUBPATH` | 这两个值怎么写 |
|---|---|
| 空（默认） | 保持默认：`http://127.0.0.1:8000`、`ws://127.0.0.1:8000` |
| `/xiaozhi-fde-talk` | 带上同一子路径：`http://127.0.0.1:8000/xiaozhi-fde-talk`、`ws://127.0.0.1:8000/xiaozhi-fde-talk` |

原理：前端 bundle 全部用相对路径（`src/api/utils.ts` 写明了「不嵌入任何后端 host」），请求里没有 host，只有 `/xiaozhi-fde-talk/api/...` 这样的路径。vite dev 的 server.proxy 会先剥掉请求里的 `/xiaozhi-fde-talk` 前缀，再把 `VITE_API_URL` / `VITE_WS_BASE_URL` 自带的路径拼回去转发——所以这两个值里带不带子路径，直接决定后端收到的请求带不带前缀。而后端配了 `SUBPATH` 后，所有 API / WS 路由都挂在前缀下（`/xiaozhi-fde-talk/api/...`），少一个前缀就 404；没配 `SUBPATH` 时路由在根路径，多一个前缀同样打不通。

dev 后端不在本地 8000 端口（docker 容器、同事机器）时，把 host:port 换掉即可，是否带子路径的规则同上。

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
cp -r dist/* backend/static/
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
127.0.0.1:xxxxx - "GET /xiaozhi-fde-talk/api/v1/auth/registration-status HTTP/1.1" 200  # 业务 API 带前缀命中路由（不剥）
127.0.0.1:xxxxx - "GET /static/js/index-xxxxx.js HTTP/1.1" 200                           # 静态资源已被剥掉前缀
```

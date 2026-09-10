# 子路径部署

生产环境默认部署在域名根路径 `/`。如果服务器根路径已经有其他项目，可以将本项目部署到子路径，例如 `/xiaozhi-fde-talk/`。

> **⚠️ 硬前提：子路径部署必须前置一层会剥掉 `/xiaozhi-fde-talk/` 前缀的反向代理（nginx / Caddy / Traefik / 云负载均衡皆可），否则不要改这个配置。**
>
> 后端的 SPA 兜底会把 `/xiaozhi-fde-talk/api/...`、`platform-config.json`、所有静态资源全部回 `200 + index.html`，前端拿 HTML 当 JSON 解析，永久白屏且无任何报错。**只跑 `pnpm build` 然后把 dist 丢到后端裸跑这条路走不通**，必须经过反向代理把前缀剥掉。

## 1. 设置前端构建路径

构建前修改 `frontend/.env.production`：

```env
VITE_PUBLIC_PATH = /xiaozhi-fde-talk/
```

如果恢复为根路径部署，将该配置改回 `/` 后重新构建。

## 2. 重新构建镜像（默认 Docker 部署）

GHCR 预构建镜像不包含本地 `VITE_PUBLIC_PATH` 改动，必须本地重打 `app` 镜像再起容器：

```bash
docker compose build app --no-cache
docker compose up -d app
```

镜像编译细节参见 [本地编译 Docker 镜像](docker-build.md)。

## 3. 配置反向代理

服务器应将 `/xiaozhi-fde-talk/` 转发到本项目服务，并保留 WebSocket 转发能力。以下是 Nginx 配置示例：

```nginx
# 不带尾斜杠访问子路径时重定向到带斜杠，避免 /xiaozhi-fde-talk 直接 404
location = /xiaozhi-fde-talk {
    return 301 /xiaozhi-fde-talk/;
}

location /xiaozhi-fde-talk/ {
    proxy_pass https://127.0.0.1:8848/;
    # WebSocket 反代必须 HTTP/1.1，否则 Upgrade 头在 HTTP/1.0 下不生效
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

`proxy_pass` 地址按实际后端协议和端口修改。配置中的结尾 `/` 会在转发时去掉 `/xiaozhi-fde-talk` 前缀，使后端继续接收 `/api/...` 和 `/ws/...` 路径。

## 4. 验证

访问 `http://服务器地址/xiaozhi-fde-talk/`，确认页面资源、API 请求和语音 WebSocket 均正常。Hash 路由页面通常会显示为 `/xiaozhi-fde-talk/#/...`。

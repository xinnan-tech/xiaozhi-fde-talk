# 子路径部署

生产环境默认部署在域名根路径 `/`。如果服务器根路径已经有其他项目，可以将本项目部署到子路径，例如 `/xiaozhi-fde-talk/`。

## 1. 设置前端构建路径

构建前修改 `frontend/.env.production`：

```env
VITE_PUBLIC_PATH = /xiaozhi-fde-talk/
```

然后重新构建：

```bash
cd frontend
pnpm build
```

如果恢复为根路径部署，将该配置改回 `/` 后重新构建。

## 2. 配置反向代理

服务器应将 `/xiaozhi-fde-talk/` 转发到本项目服务，并保留 WebSocket 转发能力。以下是 Nginx 配置示例：

```nginx
location /xiaozhi-fde-talk/ {
    proxy_pass https://127.0.0.1:8848/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

`proxy_pass` 地址按实际后端协议和端口修改。配置中的结尾 `/` 会在转发时去掉 `/xiaozhi-fde-talk` 前缀，使后端继续接收 `/api/...` 和 `/ws/...` 路径。

## 3. 验证

访问 `http://服务器地址/xiaozhi-fde-talk/`，确认页面资源、API 请求和语音 WebSocket 均正常。Hash 路由页面通常会显示为 `/xiaozhi-fde-talk/#/...`。

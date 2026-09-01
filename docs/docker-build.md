# 本地编译 Docker 镜像方法

项目已使用 GitHub Container Registry 自动构建镜像。如果你直接拉发行版镜像运行，没有自编译需求，可忽略本文档。

如果你修改了源码、想用 Docker 方式部署运行，按以下步骤操作。

## 1. 镜像分层说明

本项目采用**双镜像分层**，跟 `xiaozhi-esp32-server` 一致：

| 镜像 | Dockerfile | 内容 | 何时需要重打 |
| --- | --- | --- | --- |
| `server-base` | `Dockerfile-server-base` | python:3.12-slim + 系统依赖 + pip 国内镜像 + `backend/requirements.txt` 里的所有 Python 包 | 仅当你修改 `backend/requirements.txt` 或 `Dockerfile-server-base` |
| `server-app` | `Dockerfile-server` | `FROM` `server-base`，多阶段编译 Vue 前端 → 拷 `backend/` 源码 → 拷证书 | 你改了后端代码、前端代码、证书 |

绝大多数代码改动只需重打 `server-app`；`server-base` 改动频率低（基本只在升依赖时）。

## 2. 环境准备

安装 Docker + Buildx：

```bash
# Debian / Ubuntu
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# macOS：Docker Desktop 自带 Buildx
```

确认 Buildx 可用：

```bash
docker buildx version
```

## 3. 编译镜像

准备好三个变量：

- `<registry>`：你的镜像仓库地址。本项目上游是 `ghcr.io/xinnan-tech`，fork 后改自己用户名。例：`docker.io/yourname` 或 `ghcr.io/yourname`。
- `<base-tag>`：`server-base` 镜像的 tag。本地用 `local`，推 GHCR 用版本号。
- `<app-tag>`：`server-app` 镜像的 tag。建议用日期或自定义版本号（例：`20260901`、`1.2.3`），方便跟现网版本区分。

进入项目根目录，**先打 base 再打 app**（app 的 `FROM` 依赖 base）：

```bash
cd 项目根目录

# 1. 编译基础镜像（只装 Python 依赖；改 requirements.txt 后必跑）
docker buildx build \
  -f Dockerfile-server-base \
  -t <registry>/xiaozhi-fde-talk:<base-tag> \
  --load \
  .

# 2. 编译应用镜像（Vue 编译 + Python 源码 + 证书）
docker buildx build \
  -f Dockerfile-server \
  --build-arg SERVER_BASE_TAG=<base-tag> \
  -t <registry>/xiaozhi-fde-talk:server-app_<app-tag> \
  --load \
  .
```

> 多平台构建加 `--platform linux/amd64,linux/arm64`；需要 push 出去时加 `--push` 去掉 `--load`。

## 4. 修改 docker-compose 配置

编辑项目根目录的 `docker-compose.yml`，把 `app` 服务的镜像改成你刚编译的版本：

```yaml
services:
  app:
    image: <registry>/xiaozhi-fde-talk:server-app_<app-tag>   # 改成你的镜像地址
    # 其他字段不动
```

如果 `server-base` 也重打了，但 app 镜像用的是另一个 base tag（如 `local`），需要把 `Dockerfile-server` 里的 `ARG SERVER_BASE_TAG=server-base` 跟你的 base tag 对齐（或者在 build 时传 `--build-arg SERVER_BASE_TAG=<base-tag>`）。

## 5. 重启服务

```bash
# 停止旧容器
docker compose down

# 启动新容器
docker compose up -d
```

## 6. 验证

### 6.1 HTTPS 主服务

```bash
# -k：自签名证书跳过校验
curl -k https://localhost:8848/health
```

预期：

```json
{"status":"ok", ...}
```

### 6.2 SPA 静态托管

```bash
curl -k https://localhost:8848/
```

预期返回 HTML 页面（Vue 编译后的 `dist/index.html`）。

### 6.3 WebSocket

浏览器控制台 / `wscat`：

```
wss://localhost:8848/ws
```

### 6.4 查看日志

```bash
docker logs -f -n 100 xiaozhi_app
```

留意 lifespan 是否正常完成（`应用已启动` 一行）。

## 7. 常见问题

### Q：浏览器访问 `https://IP:8848` 报 `NET::ERR_CERT_AUTHORITY_INVALID`

A：项目自带的是自签名演示证书（与 Vite dev 用同一份）。两种处理：

1. **dev/demo**：浏览器手动点「高级 → 继续前往」（不安全），后续不再提示。
2. **生产**：用真实证书（Let's Encrypt、自签 CA 证书），把 `docker-compose.yml` 里 `./frontend/src/certs:/app/certs:ro` 这一行换成你自己的证书目录路径即可（保留 `localhost.pem` 和 `localhost-key.pem` 文件名，或同步改 `SSL_CERTFILE` / `SSL_KEYFILE` 环境变量）。

### Q：`docker compose up` 后 app 一直 restart，funasr 看起来正常

A：app 启动失败。先看日志：

```bash
docker logs xiaozhi_app
```

常见原因：

- `CORS_ORIGINS` 未配且 `ENV=prod` —— `Settings._validate_prod` 拒启。把 `ENV=prod` 改成 `ENV=dev`，或者补 `CORS_ORIGINS=https://你的域名:8848`。
- `DB_URL` 选了 MySQL/PostgreSQL 但连接不上 —— 确认数据库服务可达，账号密码正确。

### Q：多平台构建慢 / OOM

A：CI 跑多平台构建时建议加 GitHub Actions 缓存（参照 `.github/workflows/build-base-image.yml` 的 `cache-from: type=gha`）。本地手动构建时去掉 `--platform`，只跑当前架构（`--platform linux/arm64` 或 `linux/amd64`）。

### Q：`Dockerfile-server` 的 `FROM ghcr.io/xinnan-tech/xiaozhi-fde-talk:server-base` 拉不到

A：你 fork 之后需要把 `Dockerfile-server` 里的 `FROM` 改成你自己的 `<registry>` 和 `<base-tag>`，或者 build 时用 `--build-arg SERVER_BASE_REGISTRY=<registry>` 覆盖（需要把 Dockerfile 里 `FROM` 改成 `FROM ${SERVER_BASE_REGISTRY}/xiaozhi-fde-talk:${SERVER_BASE_TAG}` 形式）。

## 8. 跟 CI 的关系

本项目的 GitHub Actions 自动构建工作流（见 `.github/workflows/`）：

- `build-base-image.yml`：main 分支 push，路径匹配 `backend/requirements.txt` 或 `Dockerfile-server-base` → 构建并推 `ghcr.io/xinnan-tech/xiaozhi-fde-talk:server-base`。
- `docker-image.yml`：`v*.*.*` tag 推送 → 构建并推 `server-app_<version>` + `server-app_latest`。

本地手动编译完镜像后，建议把 tag 同步推上去（或在 CI 工作流里触发）让团队其他人也能拉到。
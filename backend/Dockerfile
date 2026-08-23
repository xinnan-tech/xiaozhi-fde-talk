# syntax=docker/dockerfile:1.7
# 多阶段构建：stage1 用 Node 编译前端 Vue 工程，stage2 把 dist/ 拷进 Python 运行时镜像。
# 这样最终镜像只需 python+deps，不带 node_modules 与构建工具，体积更小。
FROM node:20-alpine AS frontend-builder

WORKDIR /web

# 仅先拷贝锁文件，最大化缓存命中
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
# 国内常用镜像源，海外构建可换成官方 https://registry.npmjs.org/
RUN corepack enable && corepack prepare pnpm@9 --activate \
    && pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build


FROM python:3.12-alpine AS app

# bcrypt/numpy 等扩展在 Alpine 上需要编译工具链与 libffi 头文件；
# 这些 apk 包必须保留在最终镜像——运行期 bcrypt 会动态链接它们。
# 因此不剥离、注释说明权衡：保留 = 镜像 +30MB 但确保 wheel 编译成功；
# 若改用纯 musl 预编译 wheel（如改 Debian slim base），可删除这几行。
# 注：onnxruntime/llvmlite 已从 requirements.txt 移除（WS 客户端路径不 import）。
RUN apk add --no-cache \
        gcc \
        musl-dev \
        linux-headers \
        python3-dev \
        libffi-dev \
    # tini：PID 1 信号处理 + 优雅关闭子进程
    && apk add --no-cache tini

WORKDIR /app

# 先单独装依赖，源码改动不会让 pip 缓存失效
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 拷源码（.dockerignore 排除 tests/ __pycache__ 等）
COPY backend/ ./

# 前端产物从 stage1 拷过来；SERVE_FRONTEND=true 时由 FastAPI 托管
COPY --from=frontend-builder /web/dist /app/static

# SQLite + 导出目录：生产用 PG/MySQL，但 dev 模式这里仍创建 /app/data
RUN mkdir -p /app/data /app/exports

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

EXPOSE 8000

# tini 接管 PID 1 → SIGTERM 能正确传到 worker → uvicorn 走 lifespan 优雅关闭
ENTRYPOINT ["/sbin/tini", "--"]

# 默认 SQLite + dev；生产请把 ENV=prod 并切到 MySQL/PostgreSQL，
# 否则 Settings._validate_prod 会拒绝启动。
# Shell form：WEB_CONCURRENCY 环境变量展开生效；dev 默认 1 worker，compose prod 设 2~N。
# proxy-headers + forwarded-allow-ips：取反向代理后的 X-Forwarded-For，
# 让 request.client.host 拿到真实客户端 IP（否则 rate limiter 一人刷爆全员 429）。
# 默认收敛到 loopback / 私网网段（main.py 一致），公网部署需在 compose 注入
# FORWARDED_ALLOW_IPS。显式 "*" 不可信——攻击者可伪造 XFF 旁路限流桶。
CMD uvicorn app.app:create_app --factory \
    --host 0.0.0.0 --port 8000 \
    --workers ${WEB_CONCURRENCY:-1} \
    --proxy-headers \
    --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16}"
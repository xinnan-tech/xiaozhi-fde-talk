# syntax=docker/dockerfile:1.7

# ============================================================================
# Stage 1: 前端构建
# ============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build/frontend

# 启用 pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# 国内镜像加速
RUN npm config set registry https://registry.npmmirror.com

# 单独拷 lockfile 走 docker 缓存
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# 拷源码构建
COPY frontend/ ./
RUN pnpm build

# ============================================================================
# Stage 2: 后端运行时（含前端静态产物）
# ============================================================================
FROM python:3.12-slim AS runtime

WORKDIR /app

# 系统依赖（torchaudio/funasr/onnxruntime 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir \
    -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 后端代码
COPY backend/ .

# 清空 dev 阶段遗留的 static/ 内容（如 backend/static/index.html 开发测试页），
# 避免和前端 dist 产物共存冲突
RUN rm -rf static/*

# 前端构建产物注入到后端 static 目录
COPY --from=frontend-builder /build/frontend/dist ./static/

# 环境变量
ENV HOST=0.0.0.0 \
    PORT=8000 \
    SERVE_FRONTEND=true \
    PYTHONUNBUFFERED=1

# 非 root 运行：固定 uid 1001，便于宿主侧 chown 挂载卷
ENV HOME=/tmp
RUN groupadd -r app && useradd -r -u 1001 -g app app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready')" \
    || exit 1

CMD ["python", "main.py"]
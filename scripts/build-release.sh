#!/usr/bin/env bash
# 生成开源发布 tarball：剔除同事未跟踪工作树 + 构建产物 + 本地数据库。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-$(python -c "import json,sys;print(json.load(open('frontend/package.json'))['version'])" 2>/dev/null || echo 0.1.0)}"
OUT="xiaozhi-fde-talk-${VERSION}.tar.gz"

echo "==> 生成 $OUT"

# 排除项：同事工作区 / 构建产物 / 本地数据库 / 环境 / 缓存
tar --exclude='.git' \
    --exclude='docs/superpowers' \
    --exclude='.superpowers' \
    --exclude='backend/static' \
    --exclude='frontend/playwright-report' \
    --exclude='frontend/test-results' \
    --exclude='frontend/dist' \
    --exclude='frontend/build' \
    --exclude='frontend/node_modules' \
    --exclude='**/__pycache__' \
    --exclude='**/*.pyc' \
    --exclude='*.db' \
    --exclude='*.db-wal' \
    --exclude='*.db-shm' \
    --exclude='.env' \
    --exclude='backend/.env' \
    --exclude='backend/tests/e2e/.e2e.db' \
    --exclude='backend/models' \
    --exclude='.pytest_cache' \
    --exclude='funasr-runtime-resources' \
    --exclude='test-results' \
    --exclude='playwright-report' \
    --exclude='*.log' \
    --exclude='.DS_Store' \
    --exclude='.venv' \
    -czf "$OUT" \
    --transform "s,^,xiaozhi-fde-talk-${VERSION}/," \
    .

echo "==> 完成：$OUT"
ls -lh "$OUT"
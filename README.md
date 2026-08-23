<div align="center">
<img src="docs/images/banner1.png" alt="xiaozhi-fde-talk" width="100%" />

# 小智方糖xiaozhi-fde-talk

### 不只是录音转写，而是会"听你聊、提示你问"的 AI 访谈搭档

**面向 FDE、产品经理、售前、咨询师等需要频繁做客户访谈的角色**

和转写、录音工具不同，它在你访谈过程中实时分析对话，提示你"接下来该问什么、哪些关键点还没问到"，结束自动生成结构化需求报告。让每次访谈更完整、更专业，减少事后补漏。

[快速开始](#-快速开始) · [WebSocket 通信协议](docs/websocket-protocol.md) · [问题反馈](https://github.com/xinnan-tech/xiaozhi-fde-talk/issues)

</div>

## ✨ 核心特性

- 🤖 **实时辅导，告诉你该问什么**：边听边分析对话，提示"接下来该问什么、哪些关键点还没问到"，新手也能像专家一样访谈
- 🎙️ **全程实时转写**：开麦即用，流式转写实时上屏，并作为辅导引擎的输入；FunASR 本地推理，语音数据不出内网
- 📝 **结束自动出可交付报告**：不用事后整理录音，访谈结束即生成结构化需求文档，支持 Markdown / HTML / Word 导出

***

## 🚀 快速开始

### 方式一：本地开发

#### 1.1. 启动 ASR 服务（FunASR Docker）

```bash
# 首次启动会自动下载模型，完成后监听宿主机 10096 端口
docker compose up -d funasr

# 查看模型下载进度
docker compose logs -f funasr
```

后端默认 ASR 地址为 `wss://localhost:10096`，本地开发开箱即连。

#### 1.2. 启动后端

```bash
cd backend
conda create -n xiaozhi-fde-talk python=3.12 -y
conda activate xiaozhi-fde-talk
pip install -r requirements.txt
cp .env.example .env
python main.py
```

国内用户可在 `pip install` 后追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 走清华镜像加速，默认走官方 PyPI。

访谈工作台页面由后端直接托管，浏览器打开 http://localhost:8000 即用，无需单独启动前端。

#### 1.3. 首次启动：注册首位管理员

1. 浏览器打开 http://localhost:8000 → 登录弹窗自动弹出
2. 点"去注册" → 填用户名（4-32 位字母数字下划线连字符）+ 强密码 + 确认密码
3. **第一个注册的用户自动成为超级管理员**，登录后侧边栏出现"系统配置"和"用户管理"

后续用户由管理员在"用户管理"页创建。

#### 1.4. 启动前端


```bash
cd frontend
pnpm install
pnpm dev          # 默认监听 http://localhost:8848（VITE_PORT in .env.development）
```

需要打生产包给后端托管时：

```bash
pnpm build
cd ..
rm -rf backend/static/*
cp -rf frontend/dist/. backend/static/
```
执行后，访问 http://localhost:8000 即可支持前后端交互

## Security notes

JWT 当前同时写入 `localStorage` 与 `js-cookie`（见 `frontend/src/utils/auth.ts:14,39-49`）：后端 `/auth/login` 与 `/auth/register` 当前以 JSON 返回 Bearer token，前端无 httpOnly cookie 可用，只能在 JS 域可读的位置落盘。任何 XSS（含 LLM 输出中的 `<img onerror>`、依赖链供应链等）都能读走 `accessToken`，等同于会话被完整接管。报告渲染侧的 markdown-it 已硬化为 `html:false`（详见 `frontend/src/views/report/index.vue` 同段注释），是第一道闸，但不是根治。

计划迁移：后端 `/auth/login` 与 `/auth/register` 响应头追加 `Set-Cookie: authorized-token=...; HttpOnly; SameSite=Lax; Secure`，前端移除 localStorage / js-cookie 落盘并改读 `withCredentials` 请求；同时后端引入 CSRF token（双提交 cookie 或 synchronizer token pattern）应对跨站请求伪造。该迁移需后端配合，独立 issue 跟踪。

## Docker deployment

`docker-compose.yml` 提供两条服务：`funasr`（ASR）与 `app`（FastAPI + 前端 SPA）。`app` 服务用多阶段构建，第一阶段在 `node:20-alpine` 里编译 Vue 工程，第二阶段把 `dist/` 拷进 `python:3.12-alpine` 运行时。

```bash
docker compose up -d --build     # 构建并后台启动
docker compose logs -f app       # 查看 app 启动日志
docker compose ps                # 健康检查状态
```

健康检查端点 `http://localhost:8000/health` 每 30 秒探测一次，连续 3 次失败触发容器重启。

环境变量可通过 `docker-compose.yml` 的 `app.environment` 覆写：

- `ENV=dev` 是默认值；切到 `prod` 必须同时把 `DB_URL` 换成 `mysql+aiomysql://` 或 `postgresql+asyncpg://`，否则 `Settings._validate_prod` 会在启动期直接拒绝（prod 不允许 SQLite）。
- `CORS_ORIGINS` 在 shell 里 `export CORS_ORIGINS=https://talk.your-company.com` 后再 `docker compose up` 即可生效；默认值 `http://localhost:5173` 仅供本地开发。
- `ASR_WS_URL` 容器内默认连 `ws://funasr:10095`（compose 网络名），无需改。

持久化：

- `app_data` 卷挂到容器内 `/app/data`，存放 SQLite 文件。首次启动会在该目录自动创建 `xiaozhi_fde_talk.db`。
- `app_exports` 卷挂到 `/app/data`，访谈报告导出文件。

需要反代（nginx/Caddy）终止 HTTPS 时，把 `app.ports` 改成只暴露到内网（如 `"127.0.0.1:8000:8000"`），并在外层反代里透传 `Host` 与 `X-Forwarded-*`（uvicorn 已开 `--proxy-headers`）。

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

### 方式一：Docker Compose（推荐，一键启动全部服务）

`docker-compose.yml` 包含两个服务：**FunASR 语音识别** + **小智方糖主应用**，一键启动：

```bash
git clone https://gitee.com/xin-nan/xiaozhi-fde-talk.git
cd xiaozhi-fde-talk

# 复制环境变量配置（必须配置APP_ADMIN_PASSWORD，否则服务拒启）
cp backend/.env.example .env

# 启动全部服务（首次启动会下载 ASR 模型，约需 5-10 分钟）
docker-compose up -d

# 查看 FunASR 模型下载进度
docker-compose logs -f funasr
```

模型下载完成后访问 http://localhost:8000 ：

- 登录账号 `admin`，密码为 `.env` 中的 `APP_ADMIN_PASSWORD`（**必须显式设置**，否则服务拒启；密码要求 ≥ 8 位、UTF-8 字节数 ≤ 72、不能命中 `backend/app/core/password_policy.py` 内置的弱密码黑名单）
- app 容器经 compose 内网访问 FunASR：登录后到「后端配置」把 ASR 地址改为 `wss://funasr:10095`

### 方式二：本地开发

**1. 启动 ASR 服务（FunASR Docker）**

```bash
# 首次启动会自动下载模型，完成后监听宿主机 10096 端口
docker-compose up -d funasr

# 查看模型下载进度
docker-compose logs -f funasr
```

后端默认 ASR 地址为 `wss://localhost:10096`，本地开发开箱即连。

**2. 启动后端**

```bash
cd backend
conda create -n xiaozhi-fde-talk python=3.12 -y
conda activate xiaozhi-fde-talk
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
cp .env.example .env
python main.py
```

访谈工作台页面由后端直接托管，浏览器打开 http://localhost:8000 即用，无需单独启动前端。

> 💡 **运行时配置**：LLM/ASR/辅导/会话等运行期可调项，启动后访问 http://localhost:8000/ → 登录 → 切到「后端配置」tab 即可修改，保存即生效。敏感字段（API_KEY 等）显示为掩码，留空 = 保留原值。

***


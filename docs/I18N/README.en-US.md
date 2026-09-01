<div align="center">
<img src="../images/banner1-en.svg" alt="xiaozhi-fde-talk" width="100%" />

# Xiaozhi FDE Talk

### More than transcription—an AI interview copilot that listens and nudges

**For FDEs, product managers, pre-sales engineers, and consultants who run frequent customer interviews**

Unlike a transcriber or voice recorder, it analyzes the conversation in real time during your interview and nudges you on what to ask next and which key points you have not covered. As soon as the interview ends, it produces a structured requirements report so every session stays complete, professional, and free of after-the-fact gaps.

[Quick Start](#quick-start) · [WebSocket Protocol](../websocket-protocol.md) · [HTTP API](../http-api.md) · [Report an issue](https://github.com/xinnan-tech/xiaozhi-fde-talk/issues)

[![中文](https://img.shields.io/badge/%E4%B8%AD%E6%96%87-zh--CN-lightgrey.svg)](../../README.md)
[![English](https://img.shields.io/badge/English-current-green.svg)](README.en-US.md)
[![Tiếng Việt](https://img.shields.io/badge/Ti%E1%BA%BFng%20Vi%E1%BB%87t-vi--VN-lightgrey.svg)](README.vi-VN.md)

</div>

<a id="core-features"></a>

## ✨ Core Features

- 🤖 **Real-time coaching that tells you what to ask next**: it listens along and analyzes the conversation to surface the next question and the key points you have not covered yet—newcomers can run interviews like seasoned pros
- 🎙️ **Live transcription throughout**: open the mic and start; streaming transcripts appear on screen in real time and feed the coaching engine. FunASR runs locally so voice data never leaves your network
- 📝 **Auto-generated deliverables when the session ends**: no post-interview scrubbing—once the interview is over, a structured requirements document is ready to export as Markdown, HTML, or Word

***

<a id="quick-start"></a>

## 🚀 Quick Start

<a id="local-development"></a>

### Option 1: Local Development

<a id="asr-service-funasr-docker"></a>

#### 1.1. Start the ASR Service (FunASR Docker)

```bash
# The first startup downloads the model automatically; afterwards the service listens on host port 10096
docker compose up -d funasr

# Tail the model download progress
docker compose logs -f funasr
```

The backend defaults its ASR URL to `wss://localhost:10096`, provided by the system field "WebSocket URL" (seeded automatically on first run). It is not configured in `.env`—local development works out of the box.

<a id="start-the-backend"></a>

#### 1.2. Start the Backend

```bash
cd backend
conda create -n xiaozhi-fde-talk python=3.12 -y
conda activate xiaozhi-fde-talk
pip install -r requirements.txt
# Runtime data (.env, SQLite DB) lives under backend/data/; the path is resolved
# relative to backend/, not CWD — convenient for Docker volume mounts.
# .gitignore already excludes everything under data/ except the .gitkeep placeholder.
# .gitkeep seeds the dir on a normal clone, but `mkdir -p` is a safety net for
# the case where someone ran `git clean -fdx` and removed data/ along with it —
# without it the next line's `cp` would fail.
mkdir -p data
cp .env.example data/.env
python main.py
```

Users in mainland China can append `-i https://pypi.tuna.tsinghua.edu.cn/simple` to `pip install` to use the Tsinghua mirror for faster downloads; the default is the official PyPI.

After startup, the backend API docs are available at `http://localhost:8000/docs`.

<a id="start-the-frontend"></a>

#### 1.3. Start the Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

<a id="first-run-register-admin"></a>

#### 1.4. First Run: Register the First Administrator

1. Open [https://localhost:8848](https://localhost:8848) in your browser (if the browser warns "Not Secure", click through to trust the certificate).
2. Click "Go to register" → enter a username (4–32 letters, digits, underscores, or hyphens), a strong password, and confirm the password.
3. The first registered user is automatically promoted to super administrator.
4. After logging in, open System Configuration first to fill in your LLM key (otherwise interview creation will be rejected by the LLM), then click "Run Self Check" in the top-right to verify ASR, LLM, and OCR are all healthy.
5. Create an interview and try speaking.

Further reading: [User Tutorial](../user-tutorial.md)（Chinese only：register → system configuration → run an interview → export the report）.

Please note:

Because this project needs browser microphone access, when testing over a LAN the browser must use HTTPS. The repo ships with a demo certificate pair at `frontend/src/certs/localhost.pem` + `localhost-key.pem`, so it defaults to HTTPS. If you want to use your own certificate, see [User Tutorial](../user-tutorial.md) "FAQ" for how to generate one.

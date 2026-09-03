<div align="center">
<img src="../images/banner1-en.svg" alt="xiaozhi-fde-talk" width="100%" />

# Xiaozhi FDE Talk

### More than a transcriber—an AI interview copilot that listens and nudges

**For people who run customer interviews often**: FDEs, product managers, pre-sales engineers, consultants…

Regular recording tools only help you clean up after the interview. This one listens in real time and nudges you on what to ask next and what you have not covered yet. When the interview ends, you get a structured requirements report—no manual note-taking needed.

[Quick Start](#quick-start) · [Full Docs](../index.md) · [Report an issue](https://github.com/xinnan-tech/xiaozhi-fde-talk/issues)

[![中文](https://img.shields.io/badge/%E4%B8%AD%E6%96%87-zh--CN-lightgrey.svg)](../../README.md)
[![English](https://img.shields.io/badge/English-current-green.svg)](README.en-US.md)
[![Tiếng Việt](https://img.shields.io/badge/Ti%E1%BA%BFng%20Vi%E1%BB%87t-vi--VN-lightgrey.svg)](README.vi-VN.md)

</div>

## ✨ What it does

- 🤖 **Tells you what to ask, in real time**: it listens along and surfaces the next question and the key points you have not covered yet—newcomers run interviews like seasoned pros
- 🎙️ **Live transcription as you talk**: open the mic and start. The transcript feeds the coaching engine. If you use the local FunASR option, voice data never leaves your network
- 📝 **Auto-generated report when the session ends**: no post-interview scrubbing. A structured requirements document is ready to export as Markdown, HTML, or Word

***

<a id="quick-start"></a>

## 🚀 Three lines to start

You need Docker installed.

```bash
git clone https://github.com/xinnan-tech/xiaozhi-fde-talk.git
cd xiaozhi-fde-talk
docker compose up -d app
```

The first run downloads the program from the internet (a few hundred MB) and takes a minute or two.

Then open your browser and go to [https://localhost:8848](https://localhost:8848).

> Your browser will warn "Your connection is not private" or similar—don't worry. It's the demo certificate that ships with the repo. Click "Advanced" then "Proceed to localhost" to get in.

Inside, click "Register" to create your account. **The first registered user becomes the admin** and can manage everything.

Voice interviews need both the AI model and voice recognition. Without the AI key, interview creation is rejected. Without voice recognition, there is no live transcript during the interview. You can start the program first and configure both later under "System Configuration".

Full docs are [here](../index.md).

## 🚩 Configuration Guide and Recommendations
> [!Note]
> This project offers two configuration options:
>
> 1. `Starter, free` setup: suited for personal use. Every component uses a free option, no extra payment required.
>
> 2. `Commercial Pro` setup: suited for scenarios with more than 2 concurrent interviews. Faster responses and a smoother experience.
>

| Module | Starter, free | Commercial Pro |
|:---:|:---:|:---:|
| ASR (Speech Recognition) | FunASR Server (local streaming) | 👍 Doubao Stream ASR (Doubao streaming) |
| LLM (Large Model) | glm-4.7-flash (Zhipu) | 👍 qwen-plus (Aliyun Bailian) |
| OCR (Image Recognition) | Baidu OCR (Baidu Cloud OCR with a generous monthly quota) | 👍 Baidu OCR (Baidu Cloud OCR) |
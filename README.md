<div align="center">
<img src="docs/images/banner1.svg" alt="xiaozhi-fde-talk" width="100%" />

# 小智方糖xiaozhi-fde-talk

### 不只是录音转写，而是会"听你聊、提示你问"的 AI 访谈搭档

**适合需要经常做客户访谈的人**：FDE、产品经理、售前、咨询师……

普通录音工具只能事后整理。这个会在你访谈时实时分析对话，提醒你"接下来该问什么、哪些还没问到"，结束自动出结构化需求报告，让每次访谈更完整、更专业。

[文档目录](docs/index.md) · [快速开始](#-快速开始) · [问题反馈](https://github.com/xinnan-tech/xiaozhi-fde-talk/issues)

[![中文](https://img.shields.io/badge/%E4%B8%AD%E6%96%87-current-green.svg)](README.md)
[![English](https://img.shields.io/badge/English-en--US-lightgrey.svg)](docs/I18N/README.en-US.md)
[![Tiếng Việt](https://img.shields.io/badge/Ti%E1%BA%BFng%20Vi%E1%BB%87t-vi--VN-lightgrey.svg)](docs/I18N/README.vi-VN.md)

</div>

## ✨ 它能做什么

- 🤖 **实时告诉你该问什么**：边听边分析，新手也能像专家一样访谈
- 🎙️ **一边说一边实时转写**：开麦即用，转写内容同时给辅导引擎；语音数据可以全留在内网（用本地 FunASR 的话）
- 📝 **结束自动出报告**：不用事后整理录音，访谈一结束就有结构化需求文档，支持 Markdown / HTML / Word 导出

***

## 🚀 三步跑起来

需要本机装好 Docker。

```bash
git clone https://github.com/xinnan-tech/xiaozhi-fde-talk.git
cd xiaozhi-fde-talk
docker compose up -d app
```

第一次会从网上下载程序（约几百兆），耐心等一两分钟。

然后打开浏览器，访问 [https://localhost:8848](https://localhost:8848)。

> 浏览器会弹「连接不安全」——别紧张。这是开发用的演示证书，点「高级 → 继续前往 localhost」就能进。

进去后点「去注册」建账号。**第一个注册的就是管理员**，能管所有事。

跑访谈需要 AI 大模型和语音识别——不配 LLM 创建访谈会被拒，不配 ASR 访谈里说话没转写。可以先把程序跑起来，再慢慢在「系统配置」里填：

- [AI 大模型配置](docs/llm-config.md)：阿里云百炼 / DeepSeek / OpenAI 等
- [语音识别配置](docs/asr-config.md)：豆包流式 API（按量付费）或本地 FunASR（免费）

完整文档看 [这里](docs/index.md)。想本地开发（不用 Docker）看 [本地开发文档](docs/local-development.md)。
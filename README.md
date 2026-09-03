<div align="center">
<img src="docs/images/banner1.svg" alt="xiaozhi-fde-talk" width="100%" />

# 小智方糖xiaozhi-fde-talk

### 不只是录音转写，而是会"听你聊、提示你问"的 AI 访谈搭档

**面向 FDE、产品经理、售前、咨询师等需要频繁做客户访谈的角色**

和转写、录音工具不同，它在你访谈过程中实时分析对话，提示你"接下来该问什么、哪些关键点还没问到"，结束自动生成结构化需求报告。让每次访谈更完整、更专业，减少事后补漏。

[文档目录](docs/index.md) · [快速开始](#-快速开始) · [问题反馈](https://github.com/xinnan-tech/xiaozhi-fde-talk/issues)

[![中文](https://img.shields.io/badge/%E4%B8%AD%E6%96%87-current-green.svg)](README.md)
[![English](https://img.shields.io/badge/English-en--US-lightgrey.svg)](docs/I18N/README.en-US.md)
[![Tiếng Việt](https://img.shields.io/badge/Ti%E1%BA%BFng%20Vi%E1%BB%87t-vi--VN-lightgrey.svg)](docs/I18N/README.vi-VN.md)

</div>

<a id="core-features"></a>

## ✨ 核心特性

- 🤖 **实时辅导，告诉你该问什么**：边听边分析对话，提示"接下来该问什么、哪些关键点还没问到"，新手也能像专家一样访谈
- 🎙️ **全程实时转写**：开麦即用，流式转写实时上屏，并作为辅导引擎的输入；FunASR 本地推理，语音数据不出内网
- 📝 **结束自动出可交付报告**：不用事后整理录音，访谈结束即生成结构化需求文档，支持 Markdown / HTML / Word 导出

***

<a id="quick-start"></a>

## 🚀 快速开始

只需三条命令：

```bash
git clone https://github.com/xinnan-tech/xiaozhi-fde-talk.git
cd xiaozhi-fde-talk
docker compose up -d app
```

启动完成后浏览器打开 [https://localhost:8848](https://localhost:8848)（首次会弹「不安全」提示——这是自签证书的固定行为，点「高级 → 继续前往」放行），点「去注册」创建第一个超级管理员账号。

**ASR 不是必须的**：主应用启动后先注册、填 LLM 密钥就能进系统跑非语音访谈。语音识别要在「系统配置 → ASR」填好后才会启用——详见 [ASR 配置](docs/asr-config.md)（推荐火山引擎豆包流式 API 或本地免费 FunASR）。

完整文档见 [docs/index.md](docs/index.md)。开发环境部署见 [docs/local-development.md](docs/local-development.md)。
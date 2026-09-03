<div align="center">
<img src="docs/images/banner1.svg" alt="xiaozhi-fde-talk" width="100%" />

# 小智方糖xiaozhi-fde-talk

### 不只是录音转写，而是会"听你聊、提示你问"的 AI 访谈搭档

**面向 FDE、产品经理、售前、咨询师等需要频繁做客户访谈的角色**

和转写、录音工具不同，它在你访谈过程中实时分析对话，提示你"接下来该问什么、哪些关键点还没问到"，结束自动生成结构化需求报告。让每次访谈更完整、更专业，减少事后补漏。

[快速开始](#quick-start) · [完整文档](docs/index.md) · [问题反馈](https://github.com/xinnan-tech/xiaozhi-fde-talk/issues)

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

## 🚀 三句话跑起来

需要本机装好 Docker。

```bash
# 把代码拉到你电脑本地
git clone https://github.com/xinnan-tech/xiaozhi-fde-talk.git
# 进入项目目录
cd xiaozhi-fde-talk
# 启动项目
docker compose up -d app
```

第一次会从网上下载程序（约几百兆），耐心等一两分钟。

然后打开浏览器，访问 [https://localhost:8848](https://localhost:8848)。

> 浏览器会弹「连接不安全」——别紧张。这是开发用的演示证书，点「高级 → 继续前往 localhost」就能进。

进去后点「去注册」建账号。**第一个注册的就是管理员**，能管所有事。

跑访谈需要 AI 大模型和语音识别——不配 LLM 创建访谈会被拒，不配 ASR 访谈里说话没转写。可以先把程序跑起来，再慢慢在「系统配置」里配置。

完整文档看 [这里](docs/index.md)。

## 🚩 配置说明和推荐
> [!Note]
> 本项目提供两种配置方案：
> 
> 1. `入门全免费`配置：适合个人使用，所有组件均采用免费方案，无需额外付费。
> 
> 2. `流式配置`：适合超过2个并发等场景，响应速度更快，体验更佳。
> 

| 模块名称 | 入门全免费设置 | 流式配置 |
|:---:|:---:|:---:|
| ASR(语音识别) | FunASRServer(本地流式) | 👍DoubaoStreamASR(豆包流式) |
| LLM(大模型) | glm-4-flash(智谱) | 👍qwen-plus(阿里百炼) |
| OCR(图片识别) | baiduOCR(百度云OCR每月额度很多) | 👍baiduOCR(百度云OCR) |

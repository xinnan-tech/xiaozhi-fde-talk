# 图片识别配置（OCR）

点「系统配置 → OCR」进去配。

**只在访谈涉及「从图片里抽文字」时才需要**——纯语音访谈可以**完全跳过**这一节，相关功能不会受影响。

本项目支持两种：

- **百度智能云 OCR**：国内厂商，按次计费，每月都有免费额度
- **OpenAI 兼容 OCR**：用 GPT-4o 这类带视觉的模型（适合已有 OpenAI 账户的）

> OCR = Optical Character Recognition = 从图片里识别出文字。本项目用它在访谈中识别截图、合同照片等。

---

## 1. 百度智能云 OCR（推荐）

适合：国内访问稳定、价格便宜、有免费额度。

### 1.1 怎么注册开通

1. 打开 [百度智能云控制台](https://console.bce.baidu.com/)
2. 百度账号登录，做完实名认证（个人身份证或企业营业执照）
3. 进 [公有云服务 → 应用管理](https://console.bce.baidu.com/ai-engine/ocr/app/list)，点「创建应用」
4. 选「通用」下面的能力即可，提交后系统分配一个 **AK（API Key）** 和 **SK（Secret Key）**——**只在创建时显示一次**，务必复制保存

### 1.2 字段填什么

| 字段 | 填什么 |
| --- | --- |
| `type` | `baidu` |
| `base_url` | `https://aip.baidubce.com` |
| `api_key` | 上面拿到的 **AK**（API Key）|
| `secret_key` | 上面拿到的 **SK**（Secret Key）|
| `model` | `general_basic`（通用文字识别；其它可选：`accurate_basic`（高精度）、`handwriting`（手写体））|

> AK / SK 是百度用来识别「你是哪个应用」的凭证，相当于账号 + 密码。漏填一个都会报鉴权错。

### 1.3 怎么测一下通不通

1. 填好保存，点配置页右上角「运行自检」，选 OCR 卡片
2. 常见红字原因：
   - AK / SK 漏填或复制错（注意区分大小写、去掉前后空格）
   - 百度账号还没开通文字识别服务（控制台首页「已开通服务」里能看到「文字识别 OCR」）
   - 账户欠费

---

## 2. OpenAI 兼容 OCR

适合：已有 OpenAI 兼容端点 / 用 GPT-4o vision。

### 2.1 怎么注册开通

参见 [AI 大模型配置](llm-config.md) 第 3 节「OpenAI（海外）」的注册流程。API Key 共用 OpenAI 平台（也可以用 OpenRouter、Azure OpenAI 等兼容端点）。

### 2.2 字段填什么

| 字段 | 填什么 |
| --- | --- |
| `type` | `openai` |
| `base_url` | `https://api.openai.com/v1`（或你用的兼容端点）|
| `api_key` | OpenAI 平台的 API Key |
| `model` | `gpt-4o-mini`（便宜） / `gpt-4o`（强）|

> `secret_key` 字段保留空——OpenAI OCR 不用 SK。

### 2.3 怎么测一下通不通

填好保存 → 点「运行自检」选 OCR。**国内直连 OpenAI 通常不通**，需要代理或中转；用中转时 `base_url` 改成中转商端点。
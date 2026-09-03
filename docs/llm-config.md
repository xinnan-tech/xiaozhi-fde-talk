# AI 大模型配置

点「系统配置 → LLM」进去配。

不填之前创建访谈会被拒（转写出来的内容也走不了辅导）。但账号、语音识别配置、访谈列表这些都不受影响，可以先把大模型配好再开访谈。

本项目走 OpenAI 兼容协议，任意 OpenAI 兼容厂商都能用：阿里云百炼、DeepSeek、OpenAI、智谱、月之暗面、硅基流动、自建网关等。

> 「OpenAI 兼容」意思是这些厂商的 API 接口跟 OpenAI 长一样，所以代码用同一套就能对接，不用为每个厂商写专门的代码。

---

## 1. 阿里云百炼（推荐国内）

国内最省事的方案，注册送免费额度，国内访问稳定。

### 1.1 怎么注册开通

1. 打开 [阿里云百炼控制台](https://bailian.console.aliyun.com/)
2. 阿里云账号登录；首次进入会引导你完成实名认证
3. 关键两步开通：
   - **第一步：开通百炼平台**——控制台首页弹窗「开通百炼大模型服务」，按提示走完
   - **第二步：开通具体模型**——左侧菜单「模型服务」，挑模型（如 `qwen-plus`）点「开通」（新用户通常有免费 token 额度）
4. 进「API-Key」页面（左侧菜单 → 「API-Key 管理」），点「创建 API-Key」
5. **复制生成的密钥字符串**——这就是 `api_key`，**只显示一次**，关掉页面就再也看不到

### 1.2 字段填什么

| 字段 | 填什么 | 默认值 |
| --- | --- | --- |
| `type` | `openai` | ✅ |
| `base_url` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | ✅ |
| `api_key` | 上面拿到的 API-Key | （空，要填）|
| `model` | `qwen-plus` | ✅ |

> `base_url` 是「API 接入地址」（不是聊天界面的网址）；`api_key` 是「通行证」；`model` 是「用哪个模型」。

`qwen-plus` 性价比最高。要更强：`qwen3-max` / `qwen-long`；要更便宜：`qwen-turbo` / `qwen-flash`。模型名以百炼控制台实时显示为准。

### 1.3 怎么测一下通不通

1. 填好保存，点配置页右上角「运行自检」，选 LLM 卡片
2. 常见红字原因：
   - `api_key` 复制错（多了空格 / 少了字符）
   - `base_url` 填成了「聊天界面」而不是 API 地址（百炼控制台有两个入口，API 走 `compatible-mode/v1`）
   - 模型名拼错（控制台首页「我的模型」看实际开通的模型名）

---

## 2. DeepSeek

便宜、响应快，适合预算敏感或长文本场景。

### 2.1 怎么注册开通

1. 打开 [DeepSeek 开放平台](https://platform.deepseek.com/)
2. 手机号注册，做完实名认证
3. 左侧「API Keys」点「创建新密钥」，复制生成的 key（**只显示一次**）

### 2.2 字段填什么

| 字段 | 填什么 |
| --- | --- |
| `type` | `openai` |
| `base_url` | `https://api.deepseek.com/v1` |
| `api_key` | 上面拿到的 API Key |
| `model` | `deepseek-chat`（V3，通用） / `deepseek-reasoner`（R1，推理强但慢）|

### 2.3 怎么测一下通不通

填好保存 → 点「运行自检」选 LLM。失败多半是密钥错或账户欠费。

---

## 3. OpenAI（海外）

适合：海外账户、需要 GPT 系列模型。

### 3.1 怎么注册开通

1. 打开 [OpenAI Platform](https://platform.openai.com/)
2. 注册账号、绑卡（需要海外卡）
3. 左侧「API keys」点「Create new secret key」，复制（**只显示一次**）

### 3.2 字段填什么

| 字段 | 填什么 |
| --- | --- |
| `type` | `openai` |
| `base_url` | `https://api.openai.com/v1` |
| `api_key` | `sk-` 开头的密钥 |
| `model` | `gpt-4o-mini`（便宜） / `gpt-4o`（强）|

### 3.3 怎么测一下通不通

填好保存 → 点「运行自检」选 LLM。**国内直连 OpenAI 通常不通**，需要代理或中转；如果你用中转服务，`base_url` 改成中转商提供的端点即可。

---

## 4. 其它 OpenAI 兼容厂商

凡是有 OpenAI 兼容端点的厂商（智谱、月之暗面、硅基流动、自建网关等）都按以下四件套填：

| 字段 | 填什么 |
| --- | --- |
| `type` | `openai` |
| `base_url` | 厂商提供的 OpenAI 兼容端点 |
| `api_key` | 厂商给的密钥 |
| `model` | 厂商支持的模型名 |

填好保存 → 点「运行自检」选 LLM 验证即可。
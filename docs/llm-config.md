# AI 大模型配置

点「系统配置 → LLM」进去配。

不填之前创建访谈会被拒（转写出来的内容也走不了辅导）。但账号、语音识别配置、访谈列表这些都不受影响，可以先把大模型配好再开访谈。

本项目走 OpenAI 兼容协议，任意 OpenAI 兼容厂商都能用：智谱、阿里云百炼、DeepSeek、OpenAI、月之暗面、硅基流动、自建网关等。

> 「OpenAI 兼容」意思是这些厂商的 API 接口跟 OpenAI 长一样，所以代码用同一套就能对接，不用为每个厂商写专门的代码。

---

## 1. 智谱（推荐免费试用）

国内一流大模型厂商，`glm-4-flash` 完全免费，适合零成本试用。

### 1.1 怎么注册开通

1. 打开 [智谱AI 开放平台](https://open.bigmodel.cn/)
2. 手机号或微信注册，登录后完成实名认证
3. 左侧[API Keys](https://open.bigmodel.cn/apikey/platform)点「创建新密钥」，复制生成的 key（**只显示一次**）
4. 新注册账号通常自带 `glm-4-flash` 的免费额度（按 token 计量，足够日常调试）

### 1.2 字段填什么

| 字段 | 填什么 |
| --- | --- |
| `type` | `openai` |
| `base_url` | `https://open.bigmodel.cn/api/paas/v4/` |
| `api_key` | 上面拿到的 API Key |
| `model` | `glm-4-flash` |

要更强就换成收费模型：`glm-5.3`。模型名以智谱开放平台「模型广场」实时显示为准。

### 1.3 怎么测一下通不通

填好保存 → 点「运行自检」选 LLM。失败多半是：
- 密钥复制错（多了空格 / 少了字符）
- `base_url` 多写了 `/chat/completions` 之类的后缀——这里只填到 `v4/` 即可，后面的路径代码会自己拼
- 账号没实名或免费额度已用完（智谱控制台首页看「资源包」）

---

## 2. 阿里云百炼（国内访问稳定）

国内最省事的方案，注册送免费额度，国内访问稳定。

### 2.1 怎么注册开通

1. 打开 [阿里云百炼控制台](https://bailian.console.aliyun.com/)
2. 阿里云账号登录；首次进入会引导你完成实名认证
3. 关键两步开通：
   - **第一步：开通百炼平台**——控制台首页弹窗「开通百炼大模型服务」，按提示走完
   - **第二步：开通具体模型**——左侧菜单「模型服务」，挑模型（如 `qwen-plus`）点「开通」（新用户通常有免费 token 额度）
4. 进[API-Key](https://bailian.console.aliyun.com/cn-beijing?tab=model#/api-key)页面（左侧菜单 → 「API-Key 管理」），点「创建 API-Key」
5. **复制生成的密钥字符串**——这就是 `api_key`，**只显示一次**，关掉页面就再也看不到

### 2.2 字段填什么

| 字段 | 填什么 | 默认值 |
| --- | --- | --- |
| `type` | `openai` | ✅ |
| `base_url` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | ✅ |
| `api_key` | 上面拿到的 API-Key | （空，要填）|
| `model` | `qwen-plus` | ✅ |

> `base_url` 是「API 接入地址」（不是聊天界面的网址）；`api_key` 是「通行证」；`model` 是「用哪个模型」。

`qwen-plus` 性价比最高。要更强：`qwen3-max` / `qwen-long`；要更便宜：`qwen-turbo` / `qwen-flash`。模型名以百炼控制台实时显示为准。

### 2.3 怎么测一下通不通

1. 填好保存，点配置页右上角「运行自检」，选 LLM 卡片
2. 常见红字原因：
   - `api_key` 复制错（多了空格 / 少了字符）
   - `base_url` 填成了「聊天界面」而不是 API 地址（百炼控制台有两个入口，API 走 `compatible-mode/v1`）
   - 模型名拼错（控制台首页「我的模型」看实际开通的模型名）

---

## 3. DeepSeek

便宜、响应快，适合预算敏感或长文本场景。

### 3.1 怎么注册开通

1. 打开 [DeepSeek 开放平台](https://platform.deepseek.com/)
2. 手机号注册，做完实名认证
3. 左侧「API Keys」点「创建新密钥」，复制生成的 key（**只显示一次**）

### 3.2 字段填什么

| 字段 | 填什么 |
| --- | --- |
| `type` | `openai` |
| `base_url` | `https://api.deepseek.com` |
| `api_key` | 上面拿到的 API Key |
| `model` | `deepseek-v4-flash` / `deepseek-v4-pro`|

### 3.3 怎么测一下通不通

填好保存 → 点「运行自检」选 LLM。失败多半是密钥错或账户欠费。

---
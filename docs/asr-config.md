# 语音识别配置

访谈里说话靠它实时转写，不配跑不了带语音的访谈。点「系统配置 → ASR」进去配。可以先把程序跑起来，再回到这里填。

两种方案都行：

- **本地免费 FunASR**：装 Docker 在本机跑（免费，语音数据不出公司）
- **豆包流式 API**：火山引擎的（按量付费，不用跑 Docker）

> 字段里的 `第一项` 就是告诉系统用哪种识别引擎。`funasr_server` 是本地 FunASR，`doubao_stream` 是豆包流式。

---

## 1. 本地免费 FunASR（推荐内网 / 保密）

适合：不想按量付费、要求语音数据不出内网。

### 1.1 怎么开通

不用注册账号，但要先把服务跑起来：

```bash
docker compose up -d funasr
docker compose logs -f funasr
```

第一次会下载几个 G 的模型，看到日志里写「模型就绪」之类的话后，回系统配置页面继续。

### 1.2 字段填什么

| 字段 | 填什么 |
| --- | --- |
| `type` | `funasr_server` |
| `language` | `zh`（普通话）/ `yue`（粤语）/ `en`（英语）|
| `sample_rate` | `16000` |
| `ws_url` | `wss://localhost:10096`（Docker 启动后默认就是这个）|
| `ws_verify_ssl` | `false`（本地自签证书）|

### 1.3 怎么测一下通不通

1. 填好保存，点配置页右上角「运行自检」，选 ASR 卡片
2. 确认 `docker compose ps` 中 `funasr` 状态是 healthy（`Up X minutes (healthy)`）
3. 自检常见红字原因：
   - 容器没起或模型没下载完 → `docker compose logs funasr | tail -50` 看错误
   - 自检通过但访谈里没声音 → `ws_url` 写错了，FunASR 默认是 `wss://localhost:10096`

---

## 2. 火山引擎豆包流式 ASR（按量付费）

适合：不想跑 Docker、要商用稳定性、有公网出口。

### 2.1 怎么注册开通

1. 去 [火山引擎控制台](https://console.volcengine.com/)，手机号或抖音账号登录，完成实名认证
2. 在[豆包语音](https://console.volcengine.com/speech)点击[开通管理](https://console.volcengine.com/speech/new/setting/activate?projectName=default)
3. 开通「流式语音识别2.0」服务（新用户通常有免费时长），确认开通成功
4. 在[API Key](https://console.volcengine.com/speech/new/setting/apikeys?projectName=default)创建 API Key
5. 资源 ID（`resource_id`）使用 `volc.seedasr.sauc.duration`（小时版）或 `volc.seedasr.sauc.concurrent`（并发版）

### 2.2 字段填什么

| 字段 | 填什么 |
| --- | --- |
| `type` | `doubao_stream` |
| `language` | `zh-CN`（其它常见：`en-US` / `ja-JP` / `vi-VN`）|
| `sample_rate` | `16000` |
| `api_key` | 控制台创建的 API Key |
| `resource_id` | 默认 `volc.seedasr.sauc.duration`（豆包 ASR 2.0 小时版）；并发版填写 `volc.seedasr.sauc.concurrent` |
| `codec` | `raw`（2.0 协议必填，漏填或填错会导致握手失败） |
| `enable_multilingual` | `false`（除非确认要开多语种识别）|

> `api_key` 用于 API Key 鉴权。漏填或填错会导致 WebSocket 握手失败。
>
> `resource_id` 用于指定豆包 ASR 的模型版本和资源类型。默认值 `volc.seedasr.sauc.duration` 表示 2.0 小时版，适合普通测试和低并发使用；如果控制台开通的是 2.0 并发版，请改为 `volc.seedasr.sauc.concurrent`。它必须与控制台实际开通的资源一致，否则可能鉴权成功但资源不可用。
>
> 默认值只用于新安装或数据库中没有该配置的情况，已有的 `resource_id` 不会被默认值自动覆盖。

### 2.3 怎么测一下通不通

1. 填好保存，点配置页右上角「运行自检」，选 ASR 卡片
2. 常见红字原因：
   - `api_key` 填错（注意大小写、别带空格）
   - `resource_id` 与已开通的小时版/并发版资源不匹配
   - `codec` 未配或填错（2.0 协议必须 `raw`，否则握手失败）
   - 账户欠费（先看 [火山引擎账户中心](https://console.volcengine.com/user/basic-information/)）

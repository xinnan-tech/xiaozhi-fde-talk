# 语音识别配置

点「系统配置 → ASR」进去配。

不填也能用——只是访谈里说话时没有实时转写，其它功能（账号、AI 大模型配置、访谈列表）都不受影响。配好 AI 大模型后，可以先把不用语音的访谈跑起来。

本项目支持两种：

- **本地免费 FunASR**：装在内网机器上，语音数据不出公司（适合保密场景）
- **豆包流式 API**：火山引擎的（按量付费，适合商用稳定性）

> 字段里的 `type` 就是告诉系统用哪种识别引擎。`funasr_server` 是本地 FunASR，`doubao_stream` 是豆包流式。

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

1. 去 [火山引擎控制台](https://console.volcengine.com/)，手机号或抖音账号登录，做完实名认证
2. 在「语音技术」开通「流式语音识别」服务（新用户通常有免费时长）
3. 进「语音技术 → 应用管理」点「创建应用」，勾选「流式语音识别」能力
4. 应用创建成功后，进 https://console.volcengine.com/speech/service/10011 页面，开通小时版服务，复制 `服务接口认证信息` 面板里的 `APP ID` 和 `Access Token`
5. 「流式语音识别」的服务 ID（`resource_id`）：项目默认 `volc.bigasr.sauc.duration`，通常不用改

### 2.2 字段填什么

| 字段 | 填什么 |
| --- | --- |
| `type` | `doubao_stream` |
| `language` | `zh-CN`（其它常见：`en-US` / `ja-JP` / `vi-VN`）|
| `sample_rate` | `16000` |
| `appid` | 创建应用时分配的 AppID |
| `access_token` | 创建应用时和 AppID 同页给出的 Access Token |
| `resource_id` | 默认 `volc.bigasr.sauc.duration` 即可 |
| `enable_multilingual` | `false`（除非确认要开多语种识别）|

> `appid` 和 `access_token` 一起用来告诉豆包「你是谁、能不能用」。漏填一个都会报鉴权错。

### 2.3 怎么测一下通不通

1. 填好保存，点配置页右上角「运行自检」，选 ASR 卡片
2. 常见红字原因：
   - `appid` / `access_token` 填错（注意大小写、别带空格）
   - 火山引擎账号还没开通小时版服务（控制台会显示「未开通」）
   - 账户欠费（先看 [火山引擎账户中心](https://console.volcengine.com/user/basic-information/)）
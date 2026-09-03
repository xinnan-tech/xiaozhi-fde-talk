# ASR 配置

ASR 在「系统配置 → ASR」分组里配。**不配访谈里的语音识别跑不起来**——但其它功能（账号、LLM 配置、访谈列表）不受影响，配置 LLM 后可以先把非语音访谈跑通。

本项目支持的 ASR 类型：

- **funasr_server**：本地免费 FunASR（推荐内网 / 保密场景）
- **doubao_stream**：火山引擎豆包流式 API（按量付费，要商用稳定性）

---

## 1. 本地免费 FunASR（推荐内网 / 保密）

适合：不想按量付费、要求语音数据不出内网、有 GPU/CPU 资源跑模型。

### 1.1 注册 / 开通

无需注册账号。先起本地服务：

```bash
docker compose up -d funasr
docker compose logs -f funasr
```

首次启动会自动下载约几 GB 的模型，等日志显示模型就绪（看到 listening on 10095 之类）后回到系统配置页面。

### 1.2 字段填法

| 字段 | 填什么 |
| --- | --- |
| `type` | `funasr_server` |
| `language` | `zh`（普通话）/ `yue`（粤语）/ `en`（英语）|
| `sample_rate` | `16000` |
| `ws_url` | `wss://localhost:10096`（Docker 启动后默认）|
| `ws_verify_ssl` | `false`（本地自签证书）|

### 1.3 怎么测试

1. 填好保存，点配置页右上角「运行自检」，选 ASR 卡片
2. 确认 `docker compose ps` 中 `funasr` 状态为 healthy（`Up X minutes (healthy)`）
3. 自检红字常见原因：
   - 容器没起 / 没下载完模型 → `docker compose logs funasr | tail -50` 看
   - 自检通过但访谈里没声音 → `ws_url` 写错了，FunASR 默认是 `wss://localhost:10096`

---

## 2. 火山引擎豆包流式 ASR（按量付费）

适合：不想跑 Docker、要商用稳定性、有公网出口。

### 2.1 注册 / 开通

1. 打开 [火山引擎控制台](https://console.volcengine.com/)，手机号或抖音账号登录，完成实名认证
2. 在「语音技术」开通「流式语音识别」服务（新用户通常有免费时长）
3. 进入「语音技术 → 应用管理」点「创建应用」，勾选「流式语音识别」能力
4. 应用创建成功后，进入 https://console.volcengine.com/speech/service/10011 页面，开通小时版的服务，复制 `服务接口认证信息` 面板的 `APP ID` 和 `Access Token`
5. 「流式语音识别」的服务 ID（`resource_id`）：项目默认 `volc.bigasr.sauc.duration`，通常不用改

### 2.2 字段填法

| 字段 | 填什么 |
| --- | --- |
| `type` | `doubao_stream` |
| `language` | `zh-CN`（其它常见：`en-US` / `ja-JP` / `vi-VN`）|
| `sample_rate` | `16000` |
| `appid` | 创建应用时分配的 AppID |
| `access_token` | 创建应用时和 AppID 同页给出的 Access Token |
| `resource_id` | 默认 `volc.bigasr.sauc.duration` 即可 |
| `enable_multilingual` | `false`（除非确认要开多语种识别）|

### 2.3 怎么测试

1. 填好保存，点配置页右上角「运行自检」，选 ASR 卡片
2. 自检红字常见原因：
   - `appid` / `access_token` 填错
   - 火山引擎账号还没开通小时版服务（控制台会显示「未开通」）
   - 账户欠费（先看 [火山引擎账户中心](https://console.volcengine.com/user/basic-information/)）
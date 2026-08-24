# HTTP 接口约定

本文档描述本项目所有 HTTP 接口的**通用契约**：状态码语义、错误响应结构、`code` 命名规范、客户端解析方式。具体端点参数请参考路由代码（`backend/app/transport/http/routes/`）与 Pydantic schema（`backend/app/transport/http/schemas.py`）。

---

## 1. 基础约定

| 项 | 值 |
| --- | --- |
| 路径前缀 | `/api/v1`（业务）/ `/ws/v1`（WebSocket，见 `websocket-protocol.md`）|
| 数据格式 | `application/json; charset=utf-8` |
| 鉴权头 | `Authorization: Bearer <jwt>`（除白名单 `/auth/login`、`/auth/register`、`/auth/registration-status`、`/auth/refresh` 外全部必带）|
| 语言协商 | 请求头 `X-Lang` / `Accept-Language`；缺省 `zh-CN`。响应头回带 `Content-Language` |
| 时间格式 | ISO 8601 字符串（`2026-08-24T10:30:00Z`）|

---

## 2. 状态码清单

每个状态码都对应明确的**语义边界**，业务代码不混用。判断优先级：先看状态码再看 `code` 字段。

### 2.1 成功

| 状态码 | 含义 | 典型场景 |
|--------|------|---------|
| `200` | OK | 登录、查询、改密、删除等普通读写成功 |

### 2.2 4xx：客户端错误

| 状态码 | 含义 | 何时返回 | 业务 `code`（示例）|
|--------|------|---------|------------------|
| **400** | Bad Request | 业务规则违反：密码强度不够、两次密码不一致、配置值非法、状态枚举不识别、报告导出格式不支持 | `password.too_short`、`auth.password_mismatch`、`config.invalid_enum_value`、`http.report.format_unsupported` |
| **401** | Unauthorized | 认证失败：登录密码错、refresh token 过期/签名错/jti 撤销/pwd_ver 不匹配、改密时旧密码错 | `http.auth.invalid_credentials`、`auth.refresh_expired`、`auth.refresh_invalid`、`auth.refresh_revoked` |
| **403** | Forbidden | 凭证有效但行为被禁：注册已关闭、非 admin 调 admin 接口、prod 环境禁 stub LLM | `auth.registration_disabled` |
| **404** | Not Found | 资源不存在：访谈不存在、模板不存在、admin 查不到用户 / 未知配置组 | `http.session.not_found`、`http.template.not_found` |
| **409** | Conflict | 资源状态冲突：用户名已被占用、访谈状态机非法跃迁、并发上限、报告未就绪 | `auth.username_taken`、`session.illegal_transition`、`session.concurrent_limit`、`http.report.not_ready` |
| **422** | Unprocessable Entity | 请求体字段校验失败（FastAPI/Pydantic 自动触发）：字段缺失、类型错、长度超界、pattern 不匹配、extra 字段被禁 | `validation.required`、`validation.string_too_short`、`validation.string_pattern_mismatch`、`validation.extra_forbidden` |
| **429** | Too Many Requests | 触发限流：登录 / 注册 / refresh 任一桶耗尽 | `http.auth.rate_limited` |

### 2.3 5xx：服务端错误

| 状态码 | 含义 | 何时返回 | 业务 `code`（示例）|
|--------|------|---------|------------------|
| **500** | Internal Server Error | 任何未被显式捕获的未处理异常（FastAPI 默认兜底）| 无（响应体只含默认 `detail`）|
| **501** | Not Implemented | 功能未实现：报告导出请求了未支持的格式 | `report.format_not_implemented` |
| **502** | Bad Gateway | 上游不可用：ASR 服务未配置 / 连接失败 / 进程死掉 / 推流失败；LLM 未配置 / 返回不可重试错误 / 重试耗尽 / 输出非 JSON / schema 不匹配 | `asr.url_not_configured`、`asr.connect_fail`、`asr.dead`、`llm.not_configured`、`llm.retry_exhausted`、`llm.invalid_json` |
| **503** | Service Unavailable | 服务自身不可用：prod 启动时密钥未配置 | `secret.resolve_failed` |
| **504** | Gateway Timeout | 上游单次调用超时：LLM 单次超时（与 502 重试耗尽区分）| `llm.timeout` |

> ⚠️ **业务逻辑绝不抛 5xx**。所有 5xx 都对应"上游挂了 / 配置缺失 / 真出 bug"——用于运维告警与值班分流。

---

## 3. 错误响应结构

### 3.1 三种形态

| 来源 | 状态码 | Content-Type | 响应体 |
|------|--------|--------------|--------|
| **I18nError**（业务层主动抛） | 4xx / 502 / 503 / 504 | `application/json` | `{"detail": "<本地化文案>", "code": "<stable.code>"}` |
| **Pydantic RequestValidationError** | 422 | `application/json` | `{"detail": [{"type": "<errtype>", "loc": [...], "msg": "<本地化文案>"}, ...]}` |
| **裸 `HTTPException`** | 401（依赖层） / 404（SPA fallback）| `application/json` | `{"detail": "<英文短串>"}`（**无 `code` 字段**，是契约一部分）|
| **兜底 500** | 500 | `application/json` | FastAPI 默认 `{"detail": "Internal Server Error"}` |

### 3.2 I18nError 形态（绝大多数业务错误）

```http
HTTP/1.1 401 Unauthorized
Content-Language: zh-CN
Content-Type: application/json

{
  "detail": "用户名或密码错误",
  "code": "http.auth.invalid_credentials"
}
```

| 字段 | 类型 | 必有 | 说明 |
|------|------|------|------|
| `detail` | `string` | ✅ | 已按请求头 `X-Lang` / `Accept-Language` 本地化的文案。**直接展示给终端用户** |
| `code` | `string` | ✅ | 稳定机器码（不随语言变化）。客户端按 `code` 决定是否清 token、是否跳登录、是否埋点等逻辑 |
| `Content-Language` 响应头 | `string` | ✅ | 与 `detail` 的语言一致，便于客户端确认 |

**`code` 命名规范**：

```
<category>.<sub_category>[.<sub_category>].<snake_case_description>
```

- 全小写、点号分隔、末段用 snake_case
- 类别必须命中下表之一；不在表内的类别视为新增，需在 PR 中说明
- `code` 是**契约**：发布后**不能改名**（即便文案改了），改文案只改 `backend/app/core/i18n/data/*.json`，不改 `Keys`

| 类别前缀 | 范围 |
|---------|------|
| `http.*` | HTTP 路由层通用错误（鉴权、限流、404、报告导出等）|
| `auth.*` | 鉴权业务规则（用户名格式、用户名占用、密码不一致、注册关闭、refresh 系列）|
| `password.*` | 密码强度策略 |
| `session.*` | 访谈状态机（并发上限、非法跃迁、不可编辑/删除）|
| `report.*` | 报告生成与导出 |
| `config.*` | 系统配置项校验 |
| `validation.*` | Pydantic 422 字段校验（自动使用，业务代码不直接抛）|
| `llm.*` / `asr.*` / `ocr.*` | 三方适配器层错误 |
| `diag.*` | 自检接口（`/api/v1/system/diagnostics/*`）|
| `ws.*` | WebSocket 错误（与 HTTP 共享 `code` 命名空间但 transport 不同）|
| `startup.*` / `settings.*` / `secret.*` | 启动期配置校验 |

完整 `code` 列表见 `backend/app/core/i18n/messages.py` 里的 `Keys` 枚举——这是事实来源（source of truth），本文档不重复罗列以免漂移。

### 3.3 Pydantic 422 形态

```http
HTTP/1.1 422 Unprocessable Entity
Content-Language: zh-CN
Content-Type: application/json

{
  "detail": [
    {
      "type": "string_pattern_mismatch",
      "loc": ["body", "username"],
      "msg": "用户名格式不正确：4-32 位字母、数字、下划线或连字符"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `detail[].type` | `string` | Pydantic 校验类型，如 `missing` / `string_too_short` / `string_too_long` / `string_pattern_mismatch` / `extra_forbidden` |
| `detail[].loc` | `array` | 字段路径，如 `["body", "username"]`；UI 展示时取最后一段作为字段名 |
| `detail[].msg` | `string` | 已本地化的文案（由 `backend/app/app.py:_validation_handler` 按 `type` + `loc[-1]` 映射）|

> 422 响应**没有 `code` 顶层字段**——这是 FastAPI 默认形态，本项目保持一致（不强行塞 `code` 进去，避免与 I18nError 混用）。客户端按 `detail` 是数组判断为 422 即可。

### 3.4 裸 HTTPException 形态（协议边界）

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer
Content-Type: application/json

{
  "detail": "missing token"
}
```

仅在两处使用，**故意不带 `code`**：

1. `app/transport/http/dependencies.py::get_current_user` 缺 token / token 解码失败
2. SPA 兜底 `app/transport/spa_fallback.py` 未匹配到任何路由

**这是契约的一部分**：前端按"`!hasCode` 且 `status === 401`"判定"登录态失效"，清 token 并提示重新登录。一旦这处加上 `code`，前端拦截器会把它误判为业务 401，破坏流程。

---

## 4. 客户端解析指引

### 4.1 推荐做法：直接用后端 `detail`

```ts
// 前端 utils/error.ts（已实现）
import { extractBackendError } from "@/utils/error";

try {
  await api.foo();
} catch (e) {
  // 后端 detail 三种形态都能解析：
  //   - I18nError  → "用户名或密码错误"
  //   - Pydantic 422 → "username: 用户名格式不正确"
  //   - HTTPException → "missing token"（英文，但仅出现在协议边界）
  message(extractBackendError(e, t("common.request_failed")), {
    type: "error",
  });
}
```

### 4.2 按 `code` 决定行为（业务逻辑分支）

```ts
import type { AxiosError } from "axios";

function isRateLimited(e: unknown): boolean {
  const err = e as AxiosError<{ code?: string }>;
  return err?.response?.status === 429
    && err.response.data?.code === "http.auth.rate_limited";
}

function isSessionExpired(e: unknown): boolean {
  const err = e as AxiosError<{ code?: string }>;
  // 业务 401：code 存在 → 让调用方按 detail 展示
  // 凭证 401：无 code → 清 token 跳登录
  return err?.response?.status === 401 && !err.response.data?.code;
}
```

### 4.3 拦截器双保险（推荐实现）

`frontend/src/utils/http/index.ts` 的 axios 响应拦截器应：

- **裸 401**（`!hasCode`）+ 有 token：清 token + 提示登录过期
- **业务 4xx / 5xx**（`hasCode`）：主动弹一次 `detail` 文案（用 `grouping: true` 防重），即使调用方 catch 漏写 `extractBackendError` 也不会"静默失败"

> 本仓库当前拦截器已实现裸 401 清 token，但业务 4xx 仍依赖调用方各自 catch —— 见 `docs/http-api.md` §5 待办。

---

## 5. 已知偏差

| 位置 | 形态 | 原因 | 是否计划修复 |
|------|------|------|------------|
| `transport/http/dependencies.py:24,32` | 401 `{detail: "missing token" / "invalid or expired token"}` 无 code | **故意不带 code** —— 前端拦截器据此区分业务 401 与凭证失效 | **不改**（契约一部分，详见 §3.4）|
| `transport/spa_fallback.py:24` | 404 `{detail: "Not Found"}` | SPA 兜底路由，非业务接口 | 不改 |

---

历史偏差（已修复）：

- ~~`routes/reports.py` 501 改走 `I18nError(REPORT_FORMAT_NOT_IMPLEMENTED)`~~
- ~~`routes/admin_users.py` 404 改走 `I18nError(AUTH_USER_NOT_FOUND)`~~
- ~~`routes/admin_config.py` 404/422/403 改走 `I18nError` 系列（`HTTP_ADMIN_CONFIG_GROUP_NOT_FOUND` / `HTTP_ADMIN_CONFIG_UNKNOWN_KEYS` / `HTTP_ADMIN_STUB_LLM_FORBIDDEN` / `CONFIG_INVALID_ENUM_VALUE`）~~
- ~~`routes/skills.py` 404 改走 `I18nError(HTTP_SKILL_INVOKE_FAILED)`~~
- ~~`dependencies.py:42`（403 admin required）改走 `I18nError(HTTP_ADMIN_REQUIRED)`~~
- ~~`routes/interviews.py:431,434,440,446` 422/413/503/500 → 全改走 I18nError（`HTTP_OCR_IMAGE_BASE64_INVALID` / `HTTP_OCR_IMAGE_TOO_LARGE` / `OCR_NOT_CONFIGURED` / `OCR_INVOKE_FAILED`），OCR adapter 层对齐 LLM/ASR 同款 I18nError 模式~~

---

## 6. 完整 `code` → 状态码速查表

> 来源：`backend/app/core/i18n/messages.py::Keys`。下方分组对应源码注释结构。

### 6.1 HTTP 路由层

| `code` | 状态码 | 中文文案（zh-CN） |
|--------|--------|------------------|
| `http.auth.rate_limited` | 429 | 登录尝试过多，请稍后再试 |
| `http.auth.invalid_credentials` | 401 | 用户名或密码错误 |
| `http.template.not_found` | 404 | 模板不存在 |
| `http.session.not_found` | 404 | 访谈不存在 |
| `http.session.unknown_status` | 400 | 未知状态：{value} |
| `http.report.not_ready` | 409 | 报告尚未生成 |
| `http.report.format_unsupported` | 400 | 不支持的导出格式：{fmt}（支持：{supported}）|
| `http.admin.required` | 403 | 需要管理员权限 |
| `http.admin.config_group_not_found` | 404 | 配置分组不存在：{group} |
| `http.admin.config_unknown_keys` | 422 | 不允许的配置项：{unknown}（允许：{allowed}）|
| `http.admin.stub_llm_forbidden` | 403 | stub LLM 仅供测试使用，prod 环境禁止启用 |
| `http.skill.invoke_failed` | 404 | skill 调用失败：{reason} |

### 6.2 鉴权业务

| `code` | 状态码 | 中文文案 |
|--------|--------|---------|
| `auth.username_invalid_format` | 422（Pydantic 字段级 override）| 用户名格式不正确：4-32 位字母、数字、下划线或连字符 |
| `auth.username_taken` | 409 | 该用户名已被占用 |
| `auth.password_mismatch` | 400 | 两次输入的密码不一致 |
| `auth.registration_disabled` | 403 | 注册已关闭 |
| `auth.user_not_found` | 404 | 用户不存在（admin 查用户 / 重置密码场景）|
| `auth.refresh_invalid` | 401 | refresh token 无效 |
| `auth.refresh_expired` | 401 | refresh token 已过期 |
| `auth.refresh_revoked` | 401 | refresh token 已被撤销或密码已修改 |

### 6.3 密码策略

| `code` | 状态码 | 规则 |
|--------|--------|------|
| `password.too_short` | 400 | 密码为空 |
| `password.too_short_min` | 400 | 密码长度不足 {min} 位 |
| `password.too_long` | 400 | 密码过长（{byte_len} 字节 > {max}）|
| `password.charset_insufficient` | 400 | 密码字符种类不足 3 种 |
| `password.too_weak` | 400 | 密码过于简单 |

### 6.4 访谈状态机

| `code` | 状态码 |
|--------|--------|
| `session.concurrent_limit` | 409 |
| `session.illegal_transition` | 409 |
| `session.edit_forbidden` | 409 |
| `session.delete_forbidden` | 409 |

### 6.5 报告

| `code` | 状态码 |
|--------|--------|
| `report.format_not_implemented` | 501 |

### 6.6 配置项校验

| `code` | 状态码 |
|--------|--------|
| `config.invalid_enum_value` | 400 |
| `config.invalid_bool` | 400 |

### 6.7 Pydantic 422 字段校验

| `code` | Pydantic `type` |
|--------|----------------|
| `validation.required` | `missing` |
| `validation.string_too_short` | `string_too_short` |
| `validation.string_too_long` | `string_too_long` |
| `validation.string_pattern_mismatch` | `string_pattern_mismatch` |
| `validation.extra_forbidden` | `extra_forbidden` |
| `validation.invalid` | 其他兜底 |

### 6.8 LLM / ASR / OCR 适配器

| 类别 | `code` | 状态码 |
|------|--------|--------|
| LLM | `llm.not_configured` | 502 |
| LLM | `llm.non_retryable` | 502 |
| LLM | `llm.retry_exhausted` | 502 |
| LLM | `llm.no_json_block` | 502 |
| LLM | `llm.invalid_json` | 502 |
| LLM | `llm.schema_mismatch` | 502 |
| LLM | `llm.timeout` | 504 |
| ASR | `asr.url_not_configured` | 502 |
| ASR | `asr.connect_fail` | 502 |
| ASR | `asr.dead` | 502 |
| ASR | `asr.feed_fail` | 502 |
| OCR | `ocr.not_configured` | 502 |
| OCR | `ocr.invoke_failed` | 502 |
| OCR | `ocr.bad_response` | 502 |
| HTTP（路由层）| `http.ocr.image_base64_invalid` | 422 |
| HTTP（路由层）| `http.ocr.image_too_large` | 413 |

### 6.9 启动 / 配置 / 密钥

| `code` | 状态码 |
|--------|--------|
| `startup.config_invalid` | 500（启动期）|
| `startup.database_migration_fail` | 500（启动期）|
| `settings.prod_no_sqlite` | 400 |
| `settings.prod_typo_env` | 400 |
| `secret.resolve_failed` | 503 |

---

## 7. 国际化

所有用户可见文案来自 `backend/app/core/i18n/data/{locale}.json`。当前支持：

| locale | 文件 |
|--------|------|
| 简体中文 | `zh_CN.json` |
| 繁体中文 | `zh_TW.json` |
| 英文 | `en_US.json` |
| 越南语 | `vi_VN.json` |

新增语言：在该目录添加 `<locale>.json`，键集合与现有文件一致（缺失键回退到 key 名）。新增 `code`：在 `messages.py::Keys` 加枚举项 → 在所有 `data/*.json` 加键值对 → 在本文档 §6 登记。

# Frontend E2E Tests (Playwright)

## 前置依赖

- Node ≥ 20.19 或 ≥ 22.13（见 `frontend/package.json` engines）
- pnpm ≥ 9
- Python ≥ 3.11 + conda env `xiaozhi-fde-talk`（或自定义路径，见下）
- Chromium 系统库（Ubuntu 24+）：
  ```
  libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2
  libxkbcommon0 libxcomposite1 libxdamage1 libxext6 libxfixes3
  libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2
  ```
- 后端 web server：playwright.config.ts 自动拉起（8001 端口）；
  如端口被占先杀掉。
- FunASR @ `localhost:10096`（`docker compose up funasr`）
- 默认 admin 账号：`admin` / `AdminTest123!@#`
  （与 `backend/tests/conftest.py::_TEST_ADMIN_PASSWORD` 兜底一致；密码 ≥ 3 类字符，过 `password_policy` 强度校验）
- **CI 推荐注入** `E2E_ADMIN_USER` / `E2E_ADMIN_PASSWORD` 走不同测试密钥，不注入时 fallback 也满足强度要求

## Conda / Python 路径不对

`playwright.config.ts` 默认走 `$PATH` 里的 `python`。conda / pyenv / 系统
python 装在不同位置时覆盖 `E2E_PYTHON_BIN`：

```sh
E2E_PYTHON_BIN=/your/path/to/python pnpm exec playwright test
```

未注入时 shell 用 `${E2E_PYTHON_BIN:-python}` 兜底到 `$PATH` 的 `python`。

## 跑命令

```sh
pnpm exec playwright test                       # 全套
pnpm exec playwright test tests/e2e/login.spec.ts   # 单文件
pnpm exec playwright test -g "admin login"           # 单 case
pnpm exec playwright test --ui                       # Playwright UI 调试
pnpm exec playwright test --headed                   # 看浏览器
pnpm exec playwright test --trace on                 # 每条都存 trace
pnpm exec playwright show-report                     # HTML 报告
```

或走 npm scripts：

```sh
pnpm run test:e2e
pnpm run test:e2e:ui
pnpm run test:e2e:headed
pnpm run test:e2e:report
```

## 输出

- 失败时自动保存 `trace.zip` / `screenshot.png` / `video.webm` 到 `test-results/`
- HTML 报告到 `playwright-report/`
- 全套预计 ~60s；`recording.spec.ts` 单条 ~30s（用真 ASR）

## Spec 列表（10 条）

| Spec 文件 | Case 名 | 验什么 | 关键 selector |
|---|---|---|---|
| `login.spec.ts` | admin login closes dialog and lands on authenticated home | 登录成功 + 跳 home | `.login-dialog` `.login-btn` `.el-message--success` |
| `login.spec.ts` | wrong password keeps dialog open with error | 错误密码提示 | `.login-dialog` `.el-message` |
| `redirect.spec.ts` | unauthenticated visit to non-/home protected route is redirected to /home | 路由守卫 | `/\/home/` `.login-dialog` |
| `redirect.spec.ts` | authenticated visit to /home stays on /home | 已登录稳定 | `.user-avatar.online` |
| `incognito-login.spec.ts` | 隐身新用户访问 / 自动弹登录框 + 登录成功 | 新 context 首访 | `.user-avatar` `.login-dialog` |
| `create-interview.spec.ts` | creates new interview from home page | 新建访谈 → 卡片出现 | `.create-interview-dialog` `.interview-card` |
| `recording.spec.ts` | recording flow: create → navigate → start → recording status → stop | 录音链路 + ASR 流 + 徽章翻 进行中 | `.transcribing-badge` `.transcript-card` |
| `report.spec.ts` | ending an interview redirects to /home (not /report/:id) | 结束访谈 → /home | `button.session-action-primary` `.el-message-box__btns` |
| `report.spec.ts` | /reports route is reachable (parent redirect target) | /reports 可达 | body |
| `slow-network.spec.ts` | 1Mbps/200ms RTT 弱网下首屏 domcontentloaded < 8s | 弱网首屏时延 | CDP `Network.emulateNetworkConditions` |

## 已知限制（环境问题）

- FunASR 文本断言不验具体文字（模型首段推理时延不稳，30s 也不一定出字）。
  `recording.spec.ts` 只断言 `.transcript-card` 容器可见。
- 报告正文不验（LLM 未配时后端返回 `failed`，spec 只验页面骨架 `.record-page` 可见）。
- 后端 webServer 用 `reuseExistingServer: false`——并发跑两套会端口冲突。
- 后端 admin 限速：5 次/小时。重复跑前看 `_login_limiter`，必要时清 DB。

## 加新 spec

- 结构化 selector 优先：`.user-avatar` / `.login-dialog` / `.transcript-card` / `data-*`。
- 不依赖 i18n 文案 / placeholder / 颜色。
- 复用 `fixtures/admin.ts` 的 `loginAsAdmin`（已带幂等短路，重复调安全）。
- 项目默认 `use.storageState` 已带登录态；需「未登录」场景时显式 opt-out：
  ```ts
  test.use({ storageState: { cookies: [], origins: [] } })
  ```
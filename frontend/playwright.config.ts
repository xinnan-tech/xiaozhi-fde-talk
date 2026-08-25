import { defineConfig } from "@playwright/test"

// webServer 启动的 Python 子进程路径通过 E2E_PYTHON_BIN 覆盖，未注入时
// shell 端会按 `$PATH` 解析 `python` 兜底。同事 conda / pyenv / 系统 python
// 装在不同位置时：
//   E2E_PYTHON_BIN=/path/to/python pnpm exec playwright test
// 即可。CDP/FunASR 偶发抖动由 retries=1 兜底，recover 失败的真实 bug 仍会上抛。

export default defineConfig({
  testDir: "tests/e2e",
  globalSetup: "./tests/e2e/global-setup.ts",
  timeout: 30_000,
  expect: { timeout: 15_000 },
  // CDP / FunASR 偶发抖动容错一次；>1 会掩盖真 bug
  retries: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      // 每次启动 backend 前先删 e2e db：init_db 会按当前模型重建表，避免
      // 历史 65KB 累积 DB 带来 schema 漂移 / 脏数据假阳性。
      command:
        "cd ../backend && rm -f tests/e2e/.e2e.db && ${E2E_PYTHON_BIN:-python} main.py",
      port: 8001,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        // pydantic-settings 字段名是 db_url（不是 database_url），env var 用 DB_URL
        DB_URL: "sqlite+aiosqlite:///./tests/e2e/.e2e.db",
        HOST: "127.0.0.1",
        PORT: "8001",
        // e2e 不连真 FunASR：adapters/asr/factory.py 的 _read_asr_config 会优先读
        // ASR_TYPE 环境变量，funasr_mock 是离线 provider（pump_loop + asyncio），
        // 见 backend/app/adapters/asr/funasr_mock.py。
        ASR_TYPE: "funasr_mock",
      },
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "pnpm preview",
      port: 4173,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        NODE_ENV: "production",
        // 让 vite preview /api /ws 代理到 e2e 专用 8001（不走 8000 主后端）
        E2E_BACKEND_URL: "http://127.0.0.1:8001",
      },
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
  projects: [
    {
      name: "chromium",
      use: {
        browserName: "chromium",
        storageState: "tests/e2e/.auth/admin.json",
        launchOptions: {
          args: [
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            // 真 9min16s 访谈录音（opus 32kbps mono 16kHz）——chromium 接受 webm/opus 直接喂
            // MediaRecorder loop 播放，spec 跑 < 9min 永远是真语音段，FunASR 会出真文本
            `--use-file-for-fake-audio-capture=${process.cwd()}/../backend/tests/e2e/audio/interview.webm`,
          ],
        },
        permissions: ["microphone"],
      },
    },
  ],
})

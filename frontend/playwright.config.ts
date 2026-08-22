import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      // 修 task-4 留下的 harness bug：
      // 1) python 解析到 conda base env，没有 uvicorn；改用绝对路径指向项目 env
      // 2) app.main / app.app 都没有模块级 app 符号（FastAPI 实例在
      //    app.app.create_app() 内），uvicorn CLI 的 module:app 形式拿不到。
      //    改走 backend/main.py 薄壳：内部 uvicorn.run(create_app(), host, port)
      //    host/port 通过 env 注入（覆盖 backend/.env 默认 0.0.0.0:8000），
      //    APP_ADMIN_PASSWORD=longenough1234 与 tests/conftest.py 同步
      command: "cd ../backend && /home/claw/miniconda3/envs/xiaozhi-fde-talk/bin/python main.py",
      port: 8001,
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        // pydantic-settings 字段名是 db_url（不是 database_url），env var 用 DB_URL
        DB_URL: "sqlite+aiosqlite:///./tests/e2e/.e2e.db",
        HOST: "127.0.0.1",
        PORT: "8001",
        APP_ADMIN_PASSWORD: "longenough1234",
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
        launchOptions: {
          args: [
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            `--use-file-for-fake-audio-capture=${process.cwd()}/tests/e2e/fixtures/recording.wav`,
          ],
        },
        permissions: ["microphone"],
      },
    },
  ],
})
